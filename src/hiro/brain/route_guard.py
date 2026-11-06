"""Small fail-closed guard for pages whose legacy rules assume a やる気 build.

This is not a replacement strategy for other routes.  It only chooses actions
supported by current page observations and master-data recommendation metadata.
"""

from __future__ import annotations

from hiro.brain import hif_rules, route_policy
from hiro.contracts.action import Action, ActionKind
from hiro.contracts.decision import Decision
from hiro.state.catalog import CatalogUnavailable, catalog
from hiro.state.knowledge import EFFECT_JA


def _decision(action: Action, reason: str, page: str, confidence: float = 0.5) -> Decision:
    return Decision(action, reason, "rule", confidence,
                    warnings=[route_policy.ROUTE_POLICY_SKIP], decider="route_guard:" + page.lower())


def _wait(page: str, reason: str) -> Decision:
    return _decision(Action.ui(ActionKind.WAIT, why=reason), reason, page, 0.1)


def _identity(decider, state) -> str | None:
    profile = getattr(decider, "profile", None)
    return ((state.produce or {}).get("idol_card_id") or getattr(decider, "idol_card_id", None)
            or (getattr(profile, "idol_id", None) if profile else None))


def _idol_row(identity: str | None) -> dict | None:
    if not identity:
        return None
    try:
        return catalog().one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    except (CatalogUnavailable, KeyError, OSError):
        return None


def _study(decider, state, identity: str | None) -> Decision:
    page = "STUDY"
    choices = state.page_fields.get("choices") or []
    if not isinstance(choices, list) or not choices:
        return _wait(page, "非やる気路线：授業选项未识别，不按旧 profile 猜档位")
    valid = [c for c in choices if isinstance(c, dict) and type(c.get("index")) is int]
    if len(valid) != len(choices) or len({c["index"] for c in valid}) != len(valid):
        return _wait(page, "非やる気路线：授業选项索引不完整")
    row = _idol_row(identity)
    effect = (row or {}).get("examEffectType")
    plan = hif_rules.PLAN_EFFECTS.get((row or {}).get("planType"))
    name = effect.split("_", 1)[-1] if isinstance(effect, str) else None
    label = EFFECT_JA.get(name)
    if not label or not plan or name not in plan:
        return _wait(page, "非やる気路线：当前偶像的推荐效果没有可靠主数据")

    from hiro.brain.mechanism_change import enabled as change_enabled, readiness

    if change_enabled() and any(c.get("preview_seq") for c in valid):
        produce = state.produce or {}
        stamina = produce.get("stamina")
        matching = []
        for choice in valid:
            effect = "".join(str(choice.get("effect") or "").split())
            cost = choice.get("cost_hp")
            if (type(choice.get("preview_seq")) is not int or not effect or choice.get("trouble")
                    or type(cost) is not int or cost < 0 or choice.get("cost_p") not in (None, 0)
                    or (cost > 0 and (type(stamina) is not int or stamina < cost))):
                continue
            if label not in effect:
                continue
            if "セレクトチェンジ" in effect and (getattr(decider, "llm", None) is None or not readiness(state, identity)):
                continue
            matching.append(choice)
        if len(matching) == 1:
            return _decision(Action.event_select(matching[0]["index"]),
                             f"逐项预览确认 {label} 机制档、体力可付且无麻烦牌代价；换卡由成对比较执行", page, .8)
        return _wait(page, "授業预览无法确定唯一可执行的推荐机制档")

    from hiro.brain.deciders import CHANGE_STUDY_DAYS

    produce = state.produce or {}
    ps = decider.produce_state(state) if callable(getattr(decider, "produce_state", None)) else None
    mode = produce.get("mode") or (ps.mode if ps else None)
    step = produce.get("step") if produce.get("step") is not None else (ps.step if ps else None)
    day_known = isinstance(mode, str) and type(step) is int
    change_day = (mode, step) in CHANGE_STUDY_DAYS
    stamina = produce.get("stamina") if produce.get("stamina") is not None else (ps.stamina if ps else None)

    def is_change(c: dict) -> bool:
        text = "".join(str(c.get("text") or "").split())
        selected = c.get("selected") or state.page_fields.get("selected") == c["index"]
        detail = "".join(str(state.page_fields.get("effect") or "").split()) if selected else ""
        return ("セレクトチェンジ" in text + detail
                or ((change_day or not day_known) and not c.get("trouble")))

    def affordable(c: dict) -> bool:
        cost = c.get("cost_hp")
        return (type(cost) is int and cost >= 0 and
                (cost == 0 or (type(stamina) is int and stamina >= cost)))

    safe = [c for c in valid if not is_change(c) and affordable(c)]
    matching = [c for c in safe if label in str(c.get("text") or "")]
    if len(matching) == 1:
        return _decision(Action.event_select(matching[0]["index"]),
                         f"非やる気路线：授業已识别到当前偶像推荐效果 {label}，且不换卡", page, 0.8)
    # Master data fixes A/B order.  Only use it when both ordinary choices are
    # present and the observed page order makes the mapping unambiguous.
    plain = sorted((c for c in valid if not c.get("trouble")), key=lambda c: c["index"])
    if len(plain) == 2:
        recommended = plain[plan.index(name)]
        if recommended in safe:
            return _decision(Action.event_select(recommended["index"]),
                             f"非やる気路线：主数据推荐 {label}，对应已识别的授業 A/B 档且不换卡", page, 0.65)
    fallback = [c for c in safe if c.get("text") and (not c.get("trouble") or change_day)]
    if len(fallback) == 1:
        return _decision(Action.event_select(fallback[0]["index"]),
                         "非やる気路线：只选已识别且不触发换卡的授業档", page, 0.4)
    return _wait(page, "非やる気路线：无法唯一确定安全的授業档")


def _enhance(state, identity: str | None) -> Decision:
    page = "SKILL_CARD_ENHANCE"
    forced = state.page_fields.get("cancelable") is False or state.page_fields.get("trigger") == "pitem"
    cancel = Action(ActionKind.ENHANCE_CARD, {"cancel": True})
    idol = _idol_row(identity)
    if idol is not None:
        safe = []
        for c in state.page_fields.get("cards") or []:
            if not isinstance(c, dict) or not c.get("card_id") or type(c.get("index")) is not int or c.get("upgrade") != 0 or c.get("dimmed"):
                continue
            try:
                base = catalog().card(c["card_id"], 0)
                catalog().card(c["card_id"], 1)
            except (CatalogUnavailable, KeyError, OSError):
                continue
            if base.get("category") != "ProduceCardCategory_Trouble" and hif_rules.is_recommended(base, idol):
                safe.append(c)
        if safe:
            chosen = min(safe, key=lambda c: (c["card_id"], c["index"]))
            return _decision(Action(ActionKind.ENHANCE_CARD,
                                    {"card_id": chosen["card_id"], "index": chosen["index"], "upgrade": 0}),
                             "非やる気路线：强化当前偶像推荐效果的已识别可强化卡", page, 0.75)
    if forced:
        return _wait(page, "非やる気路线：必选强化页无已确认可强化推荐卡，等待复核")
    return _decision(cancel, "非やる気路线：没有已确认可强化推荐卡，取消强化", page, 0.6)


def guard(decider, page: str, state, **kw) -> Decision | None:
    """Return a guarded decision, or None to keep the exact legacy path."""
    identity = _identity(decider, state)
    uses_legacy = getattr(decider, "_uses_yaruki_policy", None)
    if (uses_legacy(state) if callable(uses_legacy) else route_policy.legacy_or_yaruki(identity)):
        return None
    if page == "SKILL_CARD_REMOVAL":
        return _decision(Action(ActionKind.REMOVE_CARD, {"cancel": True}),
                         "非やる気路线：旧删卡顺序可能删除当前路线核心，取消", page)
    if page in ("SKILL_CARD_CHANGE_1", "SKILL_CARD_CHANGE_2"):
        from hiro.brain.mechanism_change import compare, enabled
        if enabled():
            return compare(decider, state, identity, 1 if page.endswith("_1") else 2)
    if page == "SKILL_CARD_CHANGE_2":
        return _decision(Action(ActionKind.CHANGE_CARD, {"cancel": True}),
                         "非やる気路线：不按旧价值表换出卡，取消换卡", page)
    if page == "SKILL_CARD_CHANGE_1":
        return _wait(page, "非やる気路线：换卡第一页不应进入；等待人工确认")
    if page == "CONSULT":
        from hiro.brain.mechanism_consult import compare, enabled
        if enabled():
            return compare(decider, state, identity)
        return _decision(Action(ActionKind.SHOP_END), "非やる気路线：尚无适用的相談购买/删卡规则，结束相談", page)
    if page == "SPECIAL_GUIDANCE":
        return _decision(Action(ActionKind.CUSTOMIZE_END), "非やる気路线：尚无适用的特別指導定制规则，结束", page)
    if page == "HIF_ROUND_INTERVAL":
        from hiro.brain.mechanism_interval import compare, enabled
        if enabled():
            return compare(decider, state, identity)
        return _decision(Action(ActionKind.INTERVAL_END), "非やる気路线：轮间购买规则未适配，暂结束；补卡要求待实机确认", page)
    if page == "STUDY":
        return _study(decider, state, identity)
    if page == "SKILL_CARD_ENHANCE":
        from hiro.brain.mechanism_enhance import applicable, compare
        if applicable(state):
            return compare(decider, state, identity)
        return _enhance(state, identity)
    if page == "SELECT_DRINK":
        from hiro.brain.route_drink_selection import choose, enabled
        if enabled():
            return choose(decider, state, identity, can_skip=kw.get("can_skip", True), n_options=kw.get("n_options"))
        if kw.get("can_skip", True):
            return _decision(Action.exclude_card(0), "非やる気路线：饮料价值未适配，允许跳过时不拿", page, 0.3)
        return _wait(page, "非やる気路线：饮料必选但缺少适用评级，等待确认")
    if page == "PDRINK_MAX":
        decider.overflow_skip = True
        return _decision(Action(ActionKind.DISCARD_DRINK, {"discard": [], "receive": False}),
                         "非やる気路线：饮料溢出时保留现有持有，不按旧表丢弃", page, 0.5)
    return None
