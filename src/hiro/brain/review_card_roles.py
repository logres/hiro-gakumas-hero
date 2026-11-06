"""Opt-in first-exam impression roles; metadata facts stay separate from deck gaps."""

import os
import re
from dataclasses import dataclass

from hiro.brain.cards import description_text
from hiro.brain.route_policy import explicit_route_enabled
from hiro.state.catalog import CatalogUnavailable


@dataclass(frozen=True)
class ReviewRoles:
    immediate_cashout: bool
    extra_action: bool
    builds_impression: bool
    conditional: bool
    cashout_pct: int = 0


def card_roles(row: dict, *, customized: bool = False) -> ReviewRoles | None:
    text = description_text(row.get("produceDescriptions"))
    if not text or customized:
        return None  # base text does not establish customized effects
    cash = re.search(r"好印象の(\d+)%分パラメータ上昇", text)
    conditional = bool(re.search(r"場合|使用可|(?:やる気|好印象|元気|体力)消費\d+", text))
    delayed = bool(cash and re.search(r"ターン後|ターン開始時|ターン終了時|使用時|以降", text[:cash.start()]))
    return ReviewRoles(bool(cash) and not conditional and not delayed,
                       bool(re.search(r"スキルカード使用数追加\+?[1-9]\d*", text)),
                       bool(re.search(r"好印象\+[1-9]\d*", text)), conditional or delayed,
                       int(cash.group(1)) if cash and not conditional and not delayed else 0)


def cashout_preference(state, idol: dict, candidate_rows: dict[int, dict], catalog):
    """Return candidate indices, evidence strength, and an honest explanation.

    Complete reviewed decks support an absence claim. Partial records support
    only a soft preference among otherwise compatible, nonduplicate candidates.
    """
    if (os.environ.get("HIRO_REVIEW_FIRST_EXAM_ROLES") != "1" or not explicit_route_enabled()
            or idol.get("examEffectType") != "ProduceExamEffectType_ExamReview"):
        return set(), False, None
    produce = state.produce or {}
    step = produce.get("step")
    if produce.get("mode") != "produce-007" or not isinstance(step, int) or isinstance(step, bool) or not 1 <= step < 7:
        return set(), False, None
    deck = produce.get("deck")
    if not deck:
        return set(), False, None  # no observations are not evidence of an empty deck
    readable = 0
    all_readable = True
    owned_cashout_pct = 0
    owned_ids = set()
    for entry in deck:
        card = entry if isinstance(entry, dict) else vars(entry)
        if not card.get("card_id") or not isinstance(card.get("upgrade"), int):
            all_readable = False
            continue
        owned_ids.add(card["card_id"])
        try:
            roles = card_roles(catalog.card(card["card_id"], card["upgrade"]), customized=bool(card.get("customized")))
        except (CatalogUnavailable, KeyError):
            roles = None
        if roles is None:
            all_readable = False
            continue
        readable += 1
        if roles.immediate_cashout:
            owned_cashout_pct = max(owned_cashout_pct, roles.cashout_pct)
    if not readable:
        return set(), False, None
    source = state.sources.get("produce.deck")
    verified = state.field_status.get("produce.deck") == "verified" or getattr(source, "origin", None) in ("review", "screen", "event", "save")
    complete = all_readable and produce.get("deck_size") == len(deck) and verified
    raw = state.page_fields.get("candidates") or []
    candidate_roles = {i: card_roles(row, customized=bool(raw[i].get("customized"))) for i, row in candidate_rows.items()}
    if owned_cashout_pct:
        # Upgrade only within a deliberately narrow comparable set. Do not
        # displace re-action or persistent impression engines with a cash card.
        def comparable(i):
            roles = candidate_roles[i]
            if roles is None or roles.extra_action or roles.conditional:
                return False
            if roles.immediate_cashout:
                return True
            text = description_text(candidate_rows[i].get("produceDescriptions"))
            return (roles.builds_impression and "レッスン中1回" in text
                    and not re.search(r"以降|ターン開始時|ターン終了時|使用時", text))
        if not all(comparable(i) for i in candidate_rows):
            return set(), False, None
        upgrades = {i for i, roles in candidate_roles.items()
                    if roles and roles.immediate_cashout and roles.cashout_pct * 2 >= owned_cashout_pct * 3
                    and raw[i]["card_id"] not in owned_ids}
        if not upgrades:
            return set(), False, None
        scope = "已核对完整牌组" if complete else "全牌组未确认，仅按已记录牌组"
        return upgrades, False, (f"首考前兑现升级软偏好：{scope}最大无条件即时兑现为 {owned_cashout_pct}%；"
                                 "候选至少为其1.5倍且未持有；仅与普通一次性叠层或兑现比较，不压过再动或持续引擎")
    preferred = {i for i, row in candidate_rows.items()
                 if (roles := card_roles(row, customized=bool(raw[i].get("customized")))) is not None and roles.immediate_cashout}
    if not preferred:
        return set(), False, None
    reason = ("首考前：完整已核对牌组尚无无条件即时好印象兑现，优先补一张"
              if complete else "首考前：全牌组未确认，已记录卡未见无条件即时好印象兑现；同推荐与持有条件下轻量优先可确认兑现，不认定缺失")
    return preferred, complete, reason
