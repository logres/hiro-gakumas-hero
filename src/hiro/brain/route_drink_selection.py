"""Opt-in route-neutral drink choice from master effects and one model call."""

import os

from hiro.brain.cards import description_text
from hiro.contracts import Action, ActionKind, Candidate, Decision, llm_trace_from_call
from hiro.state.catalog import CatalogUnavailable, catalog


def enabled():
    return os.environ.get("HIRO_GENERIC_DRINK_SELECTION") == "1"


def build_context(state, identity, *, can_skip, n_options=None):
    """Read-only payload preparation, usable for offline review without inference."""
    if not identity:
        return None, "偶像身份未知"
    try:
        idol = catalog().one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    except (CatalogUnavailable, KeyError, OSError):
        return None, "偶像主数据未知"
    if idol.get("examEffectType") in (None, "", "ProduceExamEffectType_Unknown"):
        return None, "偶像推荐效果未知"
    fields = state.page_fields
    full = fields.get("full")
    if type(full) is not bool:
        return None, "饮料栏是否已满未知，不假设有空位"
    if full:
        return None, "饮料栏已满：本选择器不自动丢弃，需走已识别的溢出处理"
    raw = fields.get("candidates") or []
    if not isinstance(raw, list) or (n_options is not None and (type(n_options) is not int or n_options < 0)):
        return None, "饮料候选索引未知"

    def detail(drink_id):
        if not isinstance(drink_id, str) or not drink_id:
            return None
        try:
            row = catalog().one("ProduceDrink", drink_id)
        except (CatalogUnavailable, KeyError, OSError):
            return None
        text = description_text(row.get("produceDescriptions"))
        return {"drink_id": drink_id, "name": row.get("name"), "effects": text} if text else None

    candidates = []
    for index, item in enumerate(raw):
        if n_options is not None and index >= n_options:
            break
        if not isinstance(item, dict) or not item.get("drink_id"):
            continue
        if (drink := detail(item["drink_id"])) is not None:
            candidates.append({"index": index, **drink})
    if not candidates:
        return None, "没有主数据效果已确认的饮料候选"
    held_raw = fields.get("held")
    if held_raw is None and isinstance((state.produce or {}).get("drinks"), list):
        held_raw = [dict(item, index=item.get("index", i)) if isinstance(item, dict)
                    else {"index": i, "drink_id": item if isinstance(item, str) else None}
                    for i, item in enumerate(state.produce["drinks"])]
    held = None if held_raw is None else []
    if isinstance(held_raw, list):
        for item in held_raw:
            if not isinstance(item, dict):
                held.append({"unknown": True})
                continue
            known = detail(item["drink_id"]) if item.get("drink_id") else None
            held.append({"index": item.get("index"), **(known or {"unknown": True})})
    elif held_raw is not None:
        return None, "持有饮料字段格式未知"
    produce = state.produce or {}
    return {"idol": {"id": idol.get("id") or identity, "name": idol.get("name"),
                     "recommended_effect": idol["examEffectType"], "plan": idol.get("planType")},
            "stage": {"mode": produce.get("mode"), "step": produce.get("step")},
            "known_resources": {key: produce.get(key) for key in ("stamina", "max_stamina", "produce_point")},
            "held": held, "full": full, "can_skip": can_skip, "candidates": candidates}, None


def choose(decider, state, identity, *, can_skip=True, n_options=None):
    calls = []
    candidates = []

    def stop(reason):
        # Taking nothing is valid only when the actual page permits it.
        action = Action.exclude_card(0) if can_skip is True else Action.ui(ActionKind.WAIT, why=reason)
        return Decision(action, reason, "fallback", 0.1, candidates,
                        llm=[llm_trace_from_call(call) for call in calls], decider="route_drink_selection")

    payload, error = build_context(state, identity, can_skip=can_skip, n_options=n_options)
    if error:
        return stop(error)
    candidates = [Candidate(Action.activate_effect(item["index"]), preview=item) for item in payload["candidates"]]
    if decider.llm is None:
        return stop("当前路线饮料选择需要模型比较主数据效果，未配置模型；不套用干劲评级")
    try:
        data, calls = decider._ask(["route_drink_pick.md"], payload)
    except Exception as exc:
        calls = [{"adapter": getattr(decider.llm, "name", "unknown"), "model": getattr(decider.llm, "model", None),
                  "error": f"{type(exc).__name__}: {exc}"}]
        return stop("路线饮料模型调用失败，不自动选首瓶")
    if not isinstance(data, dict) or not isinstance(data.get("reason"), str) or not data["reason"].strip():
        return stop("饮料模型没有给出有效动作及理由")
    action = data.get("action")
    index = data.get("index")
    if action == "skip" and can_skip is True:
        selected = Action.exclude_card(0)
    elif action == "pick" and type(index) is int and index in {item["index"] for item in payload["candidates"]}:
        selected = Action.activate_effect(index)
    else:
        return stop("饮料模型输出越界、未知候选或不允许的跳过，停止而非套用干劲兜底")
    return Decision(selected, data["reason"].strip(), "llm", None, candidates,
                    llm=[llm_trace_from_call(call) for call in calls], decider="route_drink_selection")
