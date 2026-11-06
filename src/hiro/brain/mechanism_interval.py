"""Opt-in mechanism decisions for observed interval purchases and HP recovery."""

import os
from dataclasses import replace

from hiro.brain.mechanism_consult import _current, build_context as consult_context
from hiro.brain.route_policy import ROUTE_POLICY_SKIP, explicit_route_enabled
from hiro.contracts import Action, ActionKind, Candidate, Decision, llm_trace_from_call


def enabled():
    return explicit_route_enabled() and os.environ.get("HIRO_MECHANISM_INTERVAL") == "1"


def build_context(state, identity, master):
    if state.page.name != "HIF_ROUND_INTERVAL" or state.page_fields.get("complete") is not True:
        return None
    interval = state.page_fields.get("interval")
    if not isinstance(interval, dict) or state.page_fields.get("dialog"):
        return None
    # Reuse the current-screen budget, capacity and exact master-version checks.
    shelf = [dict(item, kind=kind) for key, kind, valid in (("cards", "card", range(4)), ("drinks", "drink", range(6, 8)))
             for item in interval.get(key) or [] if isinstance(item, dict) and type(item.get("index")) is int
             and item["index"] in valid and item.get("jewel") is not True
             and item.get("currency") in (None, "P", "produce_point")]
    fields = {**state.page_fields, "shelf": shelf}
    payload = consult_context(replace(state, page=replace(state.page, name="CONSULT"), page_fields=fields), identity, master)
    if payload is None:
        return None
    candidates = payload["candidates"]
    hp, maximum = _current(state, "stamina"), _current(state, "max_stamina")
    recover = interval.get("recover") or {}
    # The current executor implements exactly 2 HP / 10 P per slider step.
    if (recover.get("available") is True and recover.get("price_per_2hp") == 10
            and recover.get("jewel") is not True and recover.get("currency") in (None, "P", "produce_point")
            and type(hp) is int and type(maximum) is int and 0 <= hp < maximum):
        budget = payload["resources"]["produce_point"]
        for steps in range(1, min(20, (maximum - hp + 1) // 2, budget // 10) + 1):
            target = min(maximum, hp + steps * 2)
            candidates.append({"kind": "recover", "target_hp": target, "price": steps * 10,
                               "hp_before": hp, "hp_after": target, "basis": "Observed service; executor 2HP/10P steps"})
    payload["allowed_action"] = "buy listed original index, recover to listed target_hp, or end; exactly one action"
    payload["limitations"] = "No change, upgrade, customization, refresh or discard. No observed mandatory deck-size requirement; do not invent a 22-card obligation. R2 does not automatically restore HP."
    return payload


def compare(decider, state, identity):
    def end(reason, traces=()):
        return Decision(Action(ActionKind.INTERVAL_END), reason, "fallback", .3,
                        warnings=[ROUTE_POLICY_SKIP], llm=list(traces), decider="mechanism_interval")
    if not enabled() or decider.llm is None:
        return end("通用轮间未开启或未配置模型，结束；不额外消费")
    if getattr(decider, "_mechanism_interval_seq", None) == state.seq:
        return end("本帧已决定消费，等待新观测；不复用预算")
    previous = getattr(decider, "_mechanism_interval_budget", None)
    p = _current(state, "produce_point")
    if previous is not None and p is not None and p >= previous:
        return end("上次轮间消费后P点尚未确认减少；不重复消费")
    try:
        from hiro.state.catalog import catalog
        payload = build_context(state, identity, catalog())
        if not payload or not payload["candidates"]:
            return end("轮间货架、当前P点、容量或回复条件未知；无确认合法动作")
        data, calls = decider._ask(["mechanism_interval.md"], payload)
    except Exception as exc:
        return end("通用轮间上下文或模型失败：" + type(exc).__name__)
    traces = [llm_trace_from_call(call) for call in calls]
    if not isinstance(data, dict) or not isinstance(data.get("reason"), str) or not data["reason"].strip():
        return end("轮间回复无效，结束", traces)
    verb = data.get("action")
    if verb == "end" and set(data) == {"action", "reason"}:
        return end(data["reason"].strip(), traces)
    actions = []
    for item in payload["candidates"]:
        if item["kind"] == "recover":
            action = Action(ActionKind.INTERVAL_BUY, {"service": "recover", "target_hp": item["target_hp"]})
        else:
            action = Action(ActionKind.INTERVAL_BUY, {"index": item["index"]})
        actions.append(Candidate(action, preview=item))
    key = "index" if verb == "buy" else "target_hp" if verb == "recover" else None
    chosen = next((c for c in actions if key and type(data.get(key)) is int
                   and c.action.args.get(key) == data[key]), None)
    if key is None or set(data) != {"action", key, "reason"} or chosen is None:
        return end("轮间动作不在已验证白名单，结束", traces)
    decider._mechanism_interval_seq = state.seq
    decider._mechanism_interval_budget = p
    return Decision(chosen.action, data["reason"].strip(), "llm", None, actions,
                    warnings=[ROUTE_POLICY_SKIP], llm=traces, decider="mechanism_interval")
