"""Opt-in two-stage select-change planning; no route-specific value tables."""
import os
from collections import Counter
from dataclasses import replace

from hiro.brain.mechanism_card_selection import _view, build_context as card_context
from hiro.brain.route_policy import explicit_route_enabled
from hiro.contracts import Action, ActionKind, Decision, llm_trace_from_call
from hiro.state.catalog import catalog
from hiro.state.knowledge import protected_card_ids


def enabled():
    return explicit_route_enabled() and os.environ.get("HIRO_MECHANISM_CHANGE") == "1"


def _key(card):
    return card.get("card_id"), card.get("upgrade")


def _wait(reason, traces=()):
    return Decision(Action.ui(ActionKind.WAIT, why=reason), reason, "fallback", .1,
                    llm=list(traces), decider="mechanism_change")


def _outgoing(state, master):
    raw_deck = (state.produce or {}).get("deck") or []
    deck = [c if isinstance(c, dict) else vars(c) for c in raw_deck]
    counts = Counter(_key(c) for c in deck)
    protected = protected_card_ids()
    outgoing = []
    for card in deck:
        cid, up = _key(card)
        if (counts[(cid, up)] != 1 or cid in protected or card.get("customized")
                or type(up) is not int or up < 0):
            continue
        row = master.card(cid, up)
        view = _view(cid, up, row, card)
        if view["master_effect_text"] and row.get("category") != "ProduceCardCategory_Trouble":
            outgoing.append(view)
    return outgoing


def readiness(state, identity):
    """Pre-entry evidence only: no candidates exist before the irreversible study choice."""
    if not enabled() or not identity:
        return False
    try:
        master = catalog()
        idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
        payload = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
        return bool(payload["deck"]["complete"] and _outgoing(state, master))
    except Exception:
        return False


def build_context(state, identity, master):
    if not identity:
        return None
    idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    payload = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
    if not payload["deck"]["complete"]:
        return None
    outgoing = _outgoing(state, master)
    raw = state.page_fields.get("candidates") or []
    indices = Counter(c.get("index") for c in raw if isinstance(c, dict))
    incoming = []
    cols = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        idx, center = c.get("index"), c.get("center")
        if (type(idx) is not int or idx < 0 or indices[idx] != 1 or not c.get("card_id")
                or c.get("customized") or type(c.get("upgrade")) is not int
                or not isinstance(center, (list, tuple)) or len(center) != 2
                or type(center[0]) not in (int, float)):
            continue
        distances = [abs(center[0] - x) for x in (223, 362, 501)]
        column = min(range(3), key=distances.__getitem__)
        if distances[column] > 40:
            continue
        cols.append(column)
        incoming.append({**c, "column": column})
    column_counts = Counter(cols)
    pairs = []
    for new in incoming:
        if column_counts[new["column"]] != 1:
            continue
        for old in outgoing:
            # Select-change preserves the outgoing upgrade, not the preview's base version.
            row = master.card(new["card_id"], old["upgrade"])
            after = _view(new["card_id"], old["upgrade"], row, new)
            if not after["master_effect_text"] or row.get("category") == "ProduceCardCategory_Trouble":
                continue
            pairs.append({"pair_id": len(pairs), "pick_index": new["index"], "column": new["column"],
                          "outgoing": old, "incoming_after_change": after})
    payload["pairs"] = pairs
    payload["limitations"] = "No score prediction; master effects only. Upgrade inherited from outgoing. Unknown customization excluded."
    payload["allowed_action"] = "change one listed pair_id or wait; no cancellation, reroll, deletion or fallback target"
    return payload


def compare(decider, state, identity, stage):
    if not enabled() or decider.llm is None:
        return _wait("通用换卡未启用或无模型，等待")
    try:
        if stage == 1:
            decider._mechanism_change_plan = None
            payload = build_context(state, identity, catalog())
            if not payload or not payload["pairs"]:
                return _wait("换卡缺少可信完整牌组、准确效果或唯一执行映射，等待")
            payload["stage_number"] = 1
        else:
            plan = getattr(decider, "_mechanism_change_plan", None)
            cards = state.page_fields.get("cards") or []
            if (not plan or plan["identity"] != identity or plan["stage"] != {
                    "mode": (state.produce or {}).get("mode"), "step": (state.produce or {}).get("step")}
                    or state.page_fields.get("deck_complete") is not True
                    or any(not isinstance(c, dict) or not c.get("card_id") or type(c.get("upgrade")) is not int for c in cards)
                    or Counter(_key(c) for c in cards) != plan["deck_keys"]):
                return _wait("换卡阶段2与原完整牌组/阶段不一致或缺少阶段1计划，等待")
            old = plan["pair"]["outgoing"]
            matches = [c for c in cards if _key(c) == _key(old)]
            if len(matches) != 1 or matches[0].get("customized") or old["card_id"] in protected_card_ids():
                return _wait("换出卡当前映射不唯一、定制或受保护，等待")
            payload = {**plan["payload"], "stage_number": 2, "selected_pair": plan["pair"],
                       "allowed_action": "confirm original pair or wait; never substitute another target"}
        data, calls = decider._ask(["mechanism_change.md"], payload)
    except Exception as exc:
        return _wait("换卡上下文/模型失败：" + type(exc).__name__)
    traces = [llm_trace_from_call(c) for c in calls]
    if not isinstance(data, dict) or not isinstance(data.get("reason"), str) or not data["reason"].strip():
        return _wait("换卡模型回复无效", traces)
    if data.get("action") == "wait" and set(data) == {"action", "reason"}:
        return _wait(data["reason"], traces)
    if stage == 1:
        valid = {p["pair_id"]: p for p in payload["pairs"]}
        if (set(data) != {"action", "pair_id", "reason"} or data.get("action") != "change"
                or type(data.get("pair_id")) is not int or data["pair_id"] not in valid):
            return _wait("换卡配对不在白名单", traces)
        pair = valid[data["pair_id"]]
        raw = (state.produce or {}).get("deck") or []
        decider._mechanism_change_plan = {"identity": identity, "stage": payload["stage"], "pair": pair,
            "deck_keys": Counter(_key(c if isinstance(c, dict) else vars(c)) for c in raw), "payload": payload}
        args = {"stage": 1, "pick_index": pair["pick_index"], "pick_column": pair["column"], "incoming_card_id": pair["incoming_after_change"]["card_id"], "strict": True}
    else:
        if set(data) != {"action", "reason"} or data.get("action") != "confirm":
            return _wait("阶段2只允许确认原配对或等待", traces)
        old = plan["pair"]["outgoing"]
        args = {"stage": 2, "remove_card_id": old["card_id"], "remove_upgrade": old["upgrade"], "strict": True}
    return Decision(Action(ActionKind.CHANGE_CARD, args), data["reason"].strip(), "llm", None,
                    llm=traces, decider="mechanism_change")
