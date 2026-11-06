"""Opt-in, one-item mechanism comparison for ordinary CONSULT purchases only."""

import os
import sqlite3
from collections import Counter
from dataclasses import replace

from hiro.brain.cards import description_text
from hiro.brain.mechanism_card_selection import _view, build_context as card_context
from hiro.brain.route_policy import ROUTE_POLICY_SKIP, explicit_route_enabled
from hiro.contracts import Action, ActionKind, Candidate, Decision, llm_trace_from_call
from hiro.state.catalog import CatalogUnavailable, catalog


def enabled():
    return explicit_route_enabled() and os.environ.get("HIRO_MECHANISM_CONSULT") == "1"


def _current(state, key):
    """Only screen resources from this observation can authorize spending."""
    source = state.sources.get("produce." + key)
    path = "produce." + key
    if (getattr(source, "origin", None) != "screen" or getattr(source, "seq", None) != state.seq
            or path in state.pending_review or state.field_status.get(path) not in ("observed", "verified")):
        return None
    value = (state.produce or {}).get(key)
    page_value = state.page_fields.get(key)
    return value if page_value is None or page_value == value else None


def build_context(state, identity, master):
    if state.page.name != "CONSULT" or state.page_fields.get("complete") is not True:
        return None
    p = _current(state, "produce_point")
    if type(p) is not int or p < 0 or not identity:
        return None
    idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    payload = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
    payload.pop("game_recommended_index", None)
    held, capacity = _current(state, "drinks"), _current(state, "drink_capacity")
    free = (capacity - len(held) if isinstance(held, list) and type(capacity) is int
            and capacity >= len(held) and all(isinstance(x, str) and x for x in held) else None)
    payload["resources"]["produce_point"] = p
    payload["resource_field_status"] = {}
    for key in payload["resources"]:
        path = "produce." + key
        source = state.sources.get(path)
        payload["resource_field_status"][key] = {
            "origin": getattr(source, "origin", None), "seq": getattr(source, "seq", None),
            "status": state.field_status.get(path), "pending": path in state.pending_review,
            "current_screen": _current(state, key) is not None,
        }
    payload["resource_basis"] = {"produce_point": "current screen observation", "seq": state.seq,
                                 "held_drinks": held, "drink_capacity": capacity, "free_drink_slots": free,
                                 "drinks_basis": "current screen observation" if free is not None else "unknown"}
    payload["held_drink_effects"] = []
    for did in held or []:
        try:
            row = master.one("ProduceDrink", did)
            payload["held_drink_effects"].append({"drink_id": did, "name": row.get("name"),
                                                  "master_effect_text": description_text(row.get("produceDescriptions")) or None})
        except (CatalogUnavailable, KeyError, OSError, sqlite3.Error):
            payload["held_drink_effects"].append({"drink_id": did, "unknown": True})
    shelf = state.page_fields.get("shelf") or []
    counts = Counter(it.get("index") for it in shelf if isinstance(it, dict) and type(it.get("index")) is int)
    candidates = []
    for it in shelf:
        if not isinstance(it, dict):
            continue
        index, price = it.get("index"), it.get("price")
        if (type(index) is not int or index < 0 or counts[index] != 1 or type(price) is not int or price < 0
                or price > p or it.get("purchased") is not False or it.get("available") is False):
            continue
        try:
            if it.get("kind") == "card" and it.get("card_id") and type(it.get("upgrade")) is int and it["upgrade"] >= 0 and not it.get("customized"):
                row = master.card(it["card_id"], it["upgrade"])
                view = _view(it["card_id"], it["upgrade"], row, it)
            elif it.get("kind") == "drink" and it.get("drink_id") and free is not None and free > 0:
                row = master.one("ProduceDrink", it["drink_id"])
                view = {"drink_id": it["drink_id"], "name": row.get("name"),
                        "master_effect_text": description_text(row.get("produceDescriptions")) or None}
            else:
                continue
        except (CatalogUnavailable, KeyError, OSError, sqlite3.Error, ValueError, TypeError):
            continue
        if view["master_effect_text"]:
            candidates.append({"index": index, "price": price, "kind": it["kind"], **view})
    payload["candidates"] = candidates
    payload["allowed_action"] = "buy exactly one listed index or end; no delete, upgrade, refresh, discard or interval service"
    payload["limitations"] = "Only ordinary shelf purchases; deletion, upgrades, refresh and interval spending are not implemented."
    return payload


def compare(decider, state, identity):
    def end(reason, traces=()):
        return Decision(Action(ActionKind.SHOP_END), reason, "fallback", .3,
                        warnings=[ROUTE_POLICY_SKIP, "仅处理货架购买；删除/强化/刷新未实现"], llm=list(traces), decider="mechanism_consult")
    if not enabled() or decider.llm is None:
        return end("通用相談购买未开启或未配置模型，结束")
    if getattr(decider, "_mechanism_consult_purchase_seq", None) == state.seq:
        return end("购买后尚未重新观测P点，不复用旧预算")
    previous = getattr(decider, "_mechanism_consult_last_purchase", None)
    if previous is not None:
        old_p, old_index = previous
        old_item = next((it for it in state.page_fields.get("shelf") or [] if isinstance(it, dict) and it.get("index") == old_index), None)
        if _current(state, "produce_point") == old_p and old_item is not None and old_item.get("purchased") is not True:
            return end("上次购买后P点和已购标记尚未确认变化，不重复购买")
    try:
        payload = build_context(state, identity, catalog())
        if not payload or not payload["candidates"]:
            return end("当前货架/P点/容量或效果未知，没有可确认合法的购买")
        data, calls = decider._ask(["mechanism_consult.md"], payload)
    except Exception as exc:
        return end("通用相談上下文或模型失败，结束：" + type(exc).__name__)
    traces = [llm_trace_from_call(call) for call in calls]
    if not isinstance(data, dict) or not isinstance(data.get("reason"), str) or not data["reason"].strip():
        return end("通用相談回复无效，结束", traces)
    if data.get("action") == "end" and set(data) <= {"action", "reason"}:
        return end(data["reason"].strip(), traces)
    valid = {c["index"] for c in payload["candidates"]}
    if (data.get("action") != "buy" or set(data) != {"action", "index", "reason"}
            or type(data.get("index")) is not int or data["index"] not in valid):
        return end("通用相談动作不在白名单，结束", traces)
    decider._mechanism_consult_purchase_seq = state.seq
    decider._mechanism_consult_last_purchase = (payload["resources"]["produce_point"], data["index"])
    candidates = [Candidate(Action(ActionKind.SHOP_BUY, {"index": c["index"]}), preview=c) for c in payload["candidates"]]
    candidates.append(Candidate(Action(ActionKind.SHOP_END)))
    return Decision(Action(ActionKind.SHOP_BUY, {"index": data["index"]}), data["reason"].strip(), "llm", None,
                    candidates, warnings=[ROUTE_POLICY_SKIP, "仅处理货架购买；删除/强化/刷新未实现"], llm=traces, decider="mechanism_consult")
