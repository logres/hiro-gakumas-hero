"""Bounded final-turn action-drink checks using known costs and separate units."""

import os
import re
from itertools import permutations


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _ready(state):
    return (os.environ.get("HIRO_FALLBACK_DRINKS") == "1" and state.remaining_turns == 1
            and _integer(state.actions_left) and state.actions_left >= 1
            and _integer(state.hp) and _integer(state.genki)
            and not any("消費体力増加" in str(k) for k in state.buffs))


def _benefit(card):
    """One proven immediate benefit; never sum score and impression stacks."""
    if (not card.card_id or not card.text or card.tags.clears_genki or card.tags.halves_genki
            or re.search(r"場合|使用可|ターン開始時|ターン終了時|ターン後|以降|使用時", card.text)):
        return None
    if re.fullmatch(r"好印象の\d+%分パラメータ上昇(?:レッスン中1回|重複不可|\s)*", card.text):
        # A badge is an observed score, not a guessed multiplier conversion.
        if card.extra_cost or not _integer(card.badge_score) or card.badge_score == 0:
            return None
        return "score", card.badge_score
    text = card.text
    consumption = re.match(r"(好印象|やる気|元気)消費(\d+)", text)
    if consumption:
        expected = {"好印象": "ExamCostType_ExamReview", "やる気": "ExamCostType_ExamCardPlayAggressive",
                    "元気": "ExamCostType_ExamBlock"}[consumption.group(1)]
        if (not card.extra_cost or card.extra_cost.get("type") != expected
                or card.extra_cost.get("value") != int(consumption.group(2))):
            return None
        text = text[consumption.end():]
    elif card.extra_cost:
        return None  # no verified cost prefix: do not invent what it consumes
    if re.fullmatch(r"(?:(?:元気|好印象|やる気)\+[1-9]\d*|レッスン中1回|重複不可|\s)+", text):
        gain = sum(int(value) for value in re.findall(r"好印象\+([1-9]\d*)", text))
        if card.extra_cost and card.extra_cost.get("type") == "ExamCostType_ExamReview":
            value = card.extra_cost.get("value")
            if not _integer(value):
                return None
            gain -= value
        return ("impression", gain) if gain > 0 else None
    return None


def _pay(card, resources):
    if not _integer(card.cost) or not _integer(card.hp_cost):
        return None
    out = dict(resources)
    if card.extra_cost:
        key = {"ExamCostType_ExamReview": "impression", "ExamCostType_ExamCardPlayAggressive": "motivation",
               "ExamCostType_ExamBlock": "genki"}.get(card.extra_cost.get("type"))
        value = card.extra_cost.get("value")
        if key is None or not _integer(value) or not _integer(out.get(key)) or out[key] < value:
            return None
        out[key] -= value
    spent_genki = min(out["genki"], card.cost)
    out["genki"] -= spent_genki
    out["hp"] -= card.hp_cost + card.cost - spent_genki
    return out if out["hp"] >= 0 else None


def _cards(state):
    legal = set(state.legal_actions())
    return [(card, value) for card in state.hand if card.available and f"play:{card.slot}" in legal
            and not state.gives_action(card) and (value := _benefit(card)) is not None]


def _best(state, cards, limit, unit):
    options = [(card, value[1]) for card, value in cards if value[0] == unit]
    best = (0, ())
    for count in range(1, min(limit, len(options)) + 1):
        for sequence in permutations(options, count):
            resources = {"hp": state.hp, "genki": state.genki, "impression": state.impression, "motivation": state.motivation}
            for card, _ in sequence:
                resources = _pay(card, resources)
                if resources is None:
                    break
                # Ignore all positive side effects when proving affordability.
            if resources is not None and (gain := sum(value for _, value in sequence)) > best[0]:
                best = (gain, tuple(card for card, _ in sequence))
    return best


def best_direct_impression_action(state):
    """Return (slot, direct_stack_gain), or None; caller chooses route applicability."""
    if not _ready(state):
        return None
    candidates = [(card, value[1]) for card, value in _cards(state) if value[0] == "impression"
                  and _pay(card, {"hp": state.hp, "genki": state.genki,
                                  "impression": state.impression, "motivation": state.motivation}) is not None]
    if not candidates:
        return None
    card, gain = max(candidates, key=lambda item: (item[1], -item[0].cost, -item[0].slot))
    return card.slot, gain


def action_drink_decision(state):
    from hiro.brain.rules import Decision
    if not _ready(state):
        return None
    legal = set(state.legal_actions())
    if any(row.get("legal_action") in legal for row in state.action_previews or []):
        return None
    # Play an available action-neutral card before deciding to spend a drink.
    if any(card.available and card.card_id and f"play:{card.slot}" in legal and state.gives_action(card) for card in state.hand):
        return None
    drinks = [drink for drink in state.drinks if drink.drink_id and f"drink:{drink.slot}" in legal
              and re.fullmatch(r"スキルカード使用数追加\+1", drink.text.strip())]
    if not drinks:
        return None
    cards = _cards(state)
    for unit in ("score", "impression"):
        before, _ = _best(state, cards, state.actions_left, unit)
        after, sequence = _best(state, cards, state.actions_left + 1, unit)
        if after <= before or len(sequence) <= state.actions_left:
            continue
        drink = min(drinks, key=lambda item: item.slot)
        label = "当前徽章参考值（非终局分）" if unit == "score" else "直接好印象层数（非分数）"
        return Decision(f"drink:{drink.slot}", f"末回合行动饮料：已知资源可支付 {len(sequence)} 张牌；{label} {before} → {after}；"
                        "不计元气等正面副作用，喝后重新观测", "fallback")
    return None
