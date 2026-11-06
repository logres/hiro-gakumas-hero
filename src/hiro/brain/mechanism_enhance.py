"""Opt-in mechanism comparison on an already-open, proven-free enhancement page."""

import os
from collections import Counter
from dataclasses import replace

from hiro.brain.mechanism_card_selection import _view, build_context as card_context
from hiro.brain.route_policy import ROUTE_POLICY_SKIP, explicit_route_enabled
from hiro.contracts import Action, ActionKind, Candidate, Decision, llm_trace_from_call
from hiro.state.catalog import catalog


def applicable(state):
    if not (explicit_route_enabled() and os.environ.get("HIRO_MECHANISM_ENHANCE") == "1"):
        return False
    fields = state.page_fields
    # No inference from page name, cancellation controls, or a missing price.
    price_keys = ("price", "cost", "produce_point_cost")
    if any(fields.get(k) is not None for k in price_keys) or fields.get("confirm") or fields.get("services"):
        return False
    return fields.get("trigger") == "pitem" or fields.get("enhance_origin") == "event"


def build_context(state, identity, master):
    if not identity:
        return None
    idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    payload = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
    raw = state.page_fields.get("cards") or []
    ids = Counter(c.get("card_id") for c in raw if isinstance(c, dict) and c.get("card_id"))
    indices = Counter(c.get("index") for c in raw if isinstance(c, dict) and type(c.get("index")) is int)
    candidates = []
    for card in raw:
        if not isinstance(card, dict):
            continue
        cid, index = card.get("card_id"), card.get("index")
        if (not cid or ids[cid] != 1 or type(index) is not int or index < 0 or indices[index] != 1
                or type(card.get("upgrade")) is not int or card["upgrade"] != 0
                or card.get("dimmed") or card.get("customized")):
            continue
        try:
            base, upgraded = master.card(cid, 0), master.card(cid, 1)
            if base.get("category") == "ProduceCardCategory_Trouble":
                continue
            before, after = _view(cid, 0, base, card), _view(cid, 1, upgraded, card)
        except (LookupError, OSError, ValueError, TypeError):
            continue
        if before["master_effect_text"] and after["master_effect_text"]:
            candidates.append({"index": index, "card_id": cid, "before": before, "after": after,
                               "delta_basis": "Exact master versions 0→1; compare these texts, no simulated gain supplied.",
                               "execution_basis": "Unique observed card_id maps original index to existing ID-only executor."})
    payload["candidates"] = candidates
    payload["enhancement_context"] = {"trigger": state.page_fields.get("trigger"),
                                      "origin": state.page_fields.get("enhance_origin"),
                                      "cancelable": state.page_fields.get("cancelable"),
                                      "cost": "free event/item only; no purchase or service opening",
                                      "customization_effects": "unknown unless explicitly supplied; not inferred from master upgrade"}
    payload["allowed_action"] = "enhance one listed original index; cancel only when cancelable is true and not item-triggered"
    return payload


def compare(decider, state, identity):
    forced = state.page_fields.get("cancelable") is False or state.page_fields.get("trigger") == "pitem"
    can_cancel = state.page_fields.get("cancelable") is True and not forced

    def fail(reason, traces=()):
        action = Action(ActionKind.ENHANCE_CARD, {"cancel": True}) if can_cancel else Action.ui(ActionKind.WAIT, why=reason)
        return Decision(action, reason, "fallback", .2, warnings=[ROUTE_POLICY_SKIP], llm=list(traces), decider="mechanism_enhance")

    if decider.llm is None:
        return fail("免费强化未配置模型：可取消则取消，必选/按钮未知则等待")
    try:
        payload = build_context(state, identity, catalog())
        if not payload or not payload["candidates"]:
            return fail("免费强化没有可确认版本且执行映射唯一的候选")
        payload["enhancement_context"]["cancel_allowed"] = can_cancel
        data, calls = decider._ask(["mechanism_enhance.md"], payload)
    except Exception as exc:
        return fail("免费强化上下文/模型失败：" + type(exc).__name__)
    traces = [llm_trace_from_call(c) for c in calls]
    if not isinstance(data, dict) or not isinstance(data.get("reason"), str) or not data["reason"].strip():
        return fail("免费强化模型输出无效", traces)
    if data.get("action") == "cancel" and set(data) == {"action", "reason"} and can_cancel:
        return fail(data["reason"].strip(), traces)
    candidates = {c["index"]: c for c in payload["candidates"]}
    if (data.get("action") != "enhance" or set(data) != {"action", "index", "reason"}
            or type(data.get("index")) is not int or data["index"] not in candidates):
        return fail("免费强化动作不在当前白名单", traces)
    chosen = candidates[data["index"]]
    action = Action(ActionKind.ENHANCE_CARD, {"card_id": chosen["card_id"], "index": chosen["index"], "upgrade": 0})
    return Decision(action, data["reason"].strip(), "llm", None,
                    [Candidate(Action(ActionKind.ENHANCE_CARD, {"card_id": c["card_id"], "index": c["index"], "upgrade": 0}), preview=c)
                     for c in candidates.values()], warnings=[ROUTE_POLICY_SKIP], llm=traces, decider="mechanism_enhance")
