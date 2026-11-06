"""Opt-in visual review of one selected next-level customization.

This module only proposes a decision. A menu-session executor must freshly
validate its strict arguments before spending; the legacy grid executor cannot
consume these decisions safely.
"""

import json
import os
from dataclasses import replace

from hiro.brain.llm import load_prompt, prompt_version
from hiro.brain.mechanism_card_selection import _view, build_context as card_context
from hiro.brain.route_policy import ROUTE_POLICY_SKIP, explicit_route_enabled
from hiro.contracts import Action, ActionKind, Decision, llm_trace_from_call
from hiro.state.catalog import catalog


def enabled():
    return explicit_route_enabled() and os.environ.get("HIRO_MECHANISM_CUSTOMIZE") == "1"


def _wait(reason, traces=(), *, choice="wait", source="fallback"):
    return Decision(Action(ActionKind.WAIT, {"menu_session": True, "choice": choice}),
                    reason, source, .2 if source == "fallback" else None,
                    warnings=[ROUTE_POLICY_SKIP], llm=list(traces), decider="mechanism_customize")


def build_context(state, identity, review, master, *, allow_unaffordable=False):
    """Accept current screen review data, never inferred master prices or levels.

    Caller binds review and image to the same stable selected-option frame.
    OCR preview text is optional evidence, not proof of complete effect text.
    """
    if not identity or not isinstance(review, dict):
        return None
    card = review.get("selected_card") or {}
    menu = review.get("menu") or {}
    cid, up = card.get("card_id"), card.get("upgrade")
    if (not isinstance(cid, str) or not cid or type(up) is not int or up < 0 or (card.get("customized") is not False and review.get("current_effects_observed") is not True)):
        return None
    items = menu.get("items")
    if not isinstance(items, list) or any(not isinstance(it, dict) for it in items):
        return None
    indices = [it.get("item_index") for it in items]
    if (any(type(i) is not int or i not in (0, 1, 2) for i in indices)
            or len(set(indices)) != len(indices)):
        return None
    selected = [it for it in items if it.get("selected") is True]
    if len(selected) != 1:
        return None
    option = selected[0]
    preview = review.get("preview")
    if (not isinstance(preview, dict)
            or any(not isinstance(preview.get(k), dict) for k in ("before", "after"))
            or type(preview.get("selected_item_index")) is not int
            or preview["selected_item_index"] != option["item_index"]
            or any(type(preview.get(k)) is not int for k in ("price", "left", "total_left"))
            or any(preview.get(k) != option.get(k) for k in ("price", "left"))
            or preview.get("total_left") != menu.get("total_left")):
        return None
    p, price = review.get("produce_point"), option.get("price")
    if (type(p) is not int or p < 0 or type(price) is not int or price < 0 or (price > p and not allow_unaffordable)
            or option.get("available") is not True or option.get("maxed") is True
            or type(option.get("left")) is not int or option["left"] <= 0
            or type(menu.get("total_left")) is not int or menu["total_left"] <= 0):
        return None
    if review.get("view", "menu") != "menu":
        return None
    if state.page_fields.get("produce_point") is not None and state.page_fields["produce_point"] != p:
        return None
    row = master.card(cid, up)
    if not row.get("name") or row.get("category") == "ProduceCardCategory_Trouble":
        return None
    if card.get("name") is not None and card["name"].replace("＋", "+").rstrip("+") != row["name"].rstrip("+"):
        return None
    ids = row.get("produceCardCustomizeIds")
    if option.get("id") is not None:
        if not isinstance(ids, list) or option["item_index"] >= len(ids) or ids[option["item_index"]] != option["id"]:
            return None
    idol = master.one("IdolCard", identity.replace("i_card-skin-", "i_card-"))
    payload = card_context(replace(state, page_fields={"candidates": []}), idol, {}, master)
    payload["resources"]["produce_point"] = p
    payload["customize_review"] = review
    payload["reviewed_card_master"] = _view(cid, up, row, card)
    payload["reviewed_option"] = {**option, "card_id": cid, "upgrade": up, "card_name": row["name"]}
    payload["effect_basis"] = "Attached current screenshot is authoritative for visible current/after effects. OCR may be partial; base master text is not the customized preview."
    payload["allowed_action"] = "customize selected next level only, decline this option, or wait; no guidance end or automatic next level"
    payload["session_opportunity_cost"] = "Leaving this card after purchase may prevent further customization this visit. Only this next level is reviewed; other options and future levels are not presumed inferior."
    return payload


def compare_menu(decider, state, identity, review, image_jpeg):
    """Review one selected option through the shared CLI/API image adapter.

    WAIT(choice=decline) rejects only this option; WAIT(choice=wait) indicates
    uncertainty/failure. Neither authorizes leaving the menu or ending guidance.
    """
    if not enabled() or decider.llm is None:
        return _wait("通用定制未启用或无模型，等待")
    if not isinstance(image_jpeg, bytes) or not image_jpeg:
        return _wait("定制缺少当前预览图片，等待")
    try:
        payload = build_context(state, identity, review, catalog())
        if payload is None:
            return _wait("定制卡版本、价格、可用性或剩余次数未确认，等待")
        res = decider.llm.ask_json_image(load_prompt("mechanism_customize.md"),
                                       json.dumps(payload, ensure_ascii=False), image_jpeg)
        traces = [llm_trace_from_call(res.record(prompt_version=prompt_version("mechanism_customize.md")))]
        data = res.data
        if res.error:
            return _wait("定制模型失败：" + res.error, traces)
    except Exception as exc:
        return _wait("定制上下文/模型失败：" + type(exc).__name__)
    return _interpret(data, payload["reviewed_option"], traces)


def _interpret(data, opt, traces):
    if (not isinstance(data, dict) or not isinstance(data.get("reason"), str) or not data["reason"].strip()):
        return _wait("定制模型回复无效", traces)
    if data.get("action") == "wait" and set(data) == {"action", "reason"}:
        return _wait(data["reason"], traces, source="llm")
    required = {"action", "reason", "card_id", "card_name", "upgrade", "item_index", "price"}
    allowed = required | ({"customize_id"} if opt.get("id") is not None else set())
    if (not required <= set(data) or not set(data) <= allowed
            or data.get("action") not in ("customize", "decline")
            or any(type(data.get(k)) is not int or data[k] != opt[k] for k in ("upgrade", "item_index", "price"))
            or data.get("card_id") != opt["card_id"] or data.get("card_name") != opt["card_name"]
            or ("customize_id" in data and data["customize_id"] != opt.get("id"))):
        return _wait("定制模型身份、选项或价格不匹配当前预览", traces)
    if data["action"] == "decline":
        return _wait(data["reason"].strip(), traces, choice="decline", source="llm")
    args = {"menu_session": True, "item_index": opt["item_index"], "card_id": opt["card_id"],
            "upgrade": opt["upgrade"], "price": opt["price"], "levels": 1, "strict": True}
    if opt.get("id") is not None:
        args["customize_id"] = opt["id"]
    return Decision(Action(ActionKind.CUSTOMIZE_CARD, args), data["reason"].strip(), "llm", None,
                    warnings=[ROUTE_POLICY_SKIP], llm=traces, decider="mechanism_customize")


def compare_options(decider, state, identity, reviews, image_jpeg):
    """Compare all currently available next-level options for this card only.

    Image panels must appear left-to-right in reviews order. Every available
    nonmaxed menu column needs one selected preview, even if unaffordable.
    """
    if not enabled() or decider.llm is None:
        return _wait("通用定制未启用或无模型，等待")
    if not isinstance(image_jpeg, bytes) or not image_jpeg or not isinstance(reviews, list) or not reviews:
        return _wait("定制缺少完整选项预览及对比图片，等待")
    try:
        master = catalog()
        contexts = [build_context(state, identity, r, master, allow_unaffordable=True) for r in reviews]
        if any(c is None for c in contexts):
            return _wait("定制选项预览存在未知或冲突字段，等待")
        first = reviews[0]

        def snapshot(review):
            card = review["selected_card"]
            # Selected-column/highlight/preview vary; all menu facts must remain equal.
            items = sorted((it["item_index"], it.get("id"), it.get("name"), it.get("price"),
                            it.get("left"), it.get("available"), it.get("maxed"))
                           for it in review["menu"]["items"])
            return (card["card_id"], card["upgrade"], card["customized"], review["produce_point"],
                    review["menu"]["total_left"], review.get("cards_left"), items)

        if any(snapshot(r) != snapshot(first) for r in reviews[1:]):
            return _wait("定制预览不属于相同卡片与资源未变化的菜单会话，等待")
        items = first["menu"]["items"]
        if any(type(it.get("available")) is not bool for it in items):
            return _wait("菜单存在可用性未知的选项，无法完整比较")
        expected = {it["item_index"] for it in items if it.get("available") is True and it.get("maxed") is not True}
        actual = [c["reviewed_option"]["item_index"] for c in contexts]
        if len(set(actual)) != len(actual) or set(actual) != expected:
            return _wait("定制可用物理选项没有逐项完整预览，等待")
        payload = dict(contexts[0])
        payload.pop("customize_review", None)
        payload.pop("reviewed_option", None)
        options = []
        for panel, (review, context) in enumerate(zip(reviews, contexts)):
            option = context["reviewed_option"]
            options.append({**option, "image_panel_index": panel, "preview": review["preview"],
                            "affordable": option["price"] <= first["produce_point"],
                            "exclusion_reason": None if option["price"] <= first["produce_point"] else "Known current price exceeds current P; cannot select."})
        affordable = {o["item_index"]: o for o in options if o["affordable"]}
        if not affordable:
            return _wait("当前卡所有可用选项均明确超出 P 预算", choice="decline")
        payload.update(reviewed_options=options,
                       allowed_action="customize one affordable listed item_index, decline all reviewed options, or wait; current card only",
                       session_opportunity_cost="Compare only current-card next levels. Other cards and later levels are unreviewed. Leaving after purchase may prevent further customization of this card this visit.")
        prompt = "mechanism_customize_options.md"
        res = decider.llm.ask_json_image(load_prompt(prompt), json.dumps(payload, ensure_ascii=False), image_jpeg)
        traces = [llm_trace_from_call(res.record(prompt_version=prompt_version(prompt)))]
        if res.error:
            return _wait("定制比较模型失败：" + res.error, traces)
        data = res.data
        if (isinstance(data, dict) and set(data) == {"action", "reason"}
                and data.get("action") in ("decline", "wait")
                and isinstance(data.get("reason"), str) and data["reason"].strip()):
            return _wait(data["reason"].strip(), traces, choice=data["action"], source="llm")
        if (not isinstance(data, dict) or data.get("action") != "customize"
                or type(data.get("item_index")) is not int or data["item_index"] not in affordable):
            return _wait("定制比较回复未选择已审阅且可支付的选项", traces)
        return _interpret(data, affordable[data["item_index"]], traces)
    except Exception as exc:
        return _wait("定制比较上下文/模型失败：" + type(exc).__name__)
