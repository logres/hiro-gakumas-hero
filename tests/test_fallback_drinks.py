import json
from pathlib import Path

import pytest

from hiro.brain.cards import CardView, DrinkView, parse_tags
from hiro.brain.fallback_drinks import action_drink_decision, best_direct_impression_action
from hiro.brain.rules import fallback
from hiro.brain.state import BattleState


def card(slot, gain, cost=2):
    text = f"好印象+{gain}レッスン中1回"
    return CardView(slot, str(slot), f"card-{slot}", 0, True, "mental", cost, 0, None, text, parse_tags("", text))


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv("HIRO_FALLBACK_DRINKS", "1")
    return BattleState("qualify-1", 9, 1, 10, 45, 0, [card(0, 10, 8), card(1, 3)],
                       drinks=[DrinkView(1, "action", "drink-action", "スキルカード使用数追加+1")],
                       actions_left=1, impression=24, motivation=10)


def test_default_off_preserves_fallback(state, monkeypatch):
    monkeypatch.delenv("HIRO_FALLBACK_DRINKS", raising=False)
    assert action_drink_decision(state) is None
    assert fallback(state).kind != "drink"


def test_action_drink_requires_additional_affordable_benefit(state):
    result = fallback(state)
    assert result.action == "drink:1" and "10 → 13" in result.reason and "非分数" in result.reason
    assert best_direct_impression_action(state) == (0, 10)


@pytest.mark.parametrize("field,value", [("actions_left", 0), ("actions_left", None), ("hp", None),
                                         ("genki", None), ("remaining_turns", 2), ("remaining_turns", None)])
def test_unknown_resources_zero_actions_or_not_final_turn_never_spend(state, field, value):
    setattr(state, field, value)
    assert action_drink_decision(state) is None


@pytest.mark.parametrize("blocked", [["drink:1"], ["play:0"], ["play:1"]])
def test_blocked_drink_or_needed_card_prevents_spending(state, blocked):
    state.blocked = blocked
    assert action_drink_decision(state) is None


def test_no_additional_value_when_actions_already_suffice_or_only_one_card(state):
    state.actions_left = 2
    assert action_drink_decision(state) is None
    state.actions_left = 1
    state.hand = state.hand[:1]
    assert action_drink_decision(state) is None


@pytest.mark.parametrize("problem", ["combined_hp", "direct_hp", "unknown_cost", "unknown_extra", "unaffordable_extra", "unknown_extra_resource", "cost_increase"])
def test_real_cost_fields_must_support_the_whole_sequence(state, problem):
    if problem == "combined_hp":
        state.hp = 9
    elif problem == "direct_hp":
        state.hand[1].hp_cost = 1
    elif problem == "unknown_cost":
        state.hand[1].cost = None
    elif problem == "unknown_extra":
        state.hand[1].extra_cost = {"type": "unknown", "value": 1}
    elif problem in ("unaffordable_extra", "unknown_extra_resource"):
        state.hand[1].extra_cost = {"type": "ExamCostType_ExamCardPlayAggressive", "value": 11}
        if problem == "unknown_extra_resource":
            state.motivation = None
    else:
        state.buffs = {"消費体力増加": None}
    assert action_drink_decision(state) is None


def test_known_extra_cost_is_paid_and_positive_side_effects_are_not_needed(state):
    state.hand[1].extra_cost = {"type": "ExamCostType_ExamCardPlayAggressive", "value": 2}
    state.hand[1].text = "やる気消費2" + state.hand[1].text
    assert action_drink_decision(state).action == "drink:1"


@pytest.mark.parametrize("suffix", ["好印象を0にする", "好印象を半分にする", "未知の効果"])
def test_unrecognized_or_negative_side_effects_are_not_hidden_by_positive_prefix(state, suffix):
    state.hand[1].text += suffix
    assert action_drink_decision(state) is None


def test_cost_prefix_requires_matching_known_resource_metadata(state):
    state.hand[1].text = "やる気消費2" + state.hand[1].text
    assert action_drink_decision(state) is None
    state.hand[1].extra_cost = {"type": "ExamCostType_ExamReview", "value": 2}
    assert action_drink_decision(state) is None


def test_previews_keep_priority_and_copy_is_not_supported(state):
    state.action_previews = [{"legal_action": "play:1", "期望终局分": 12345}]
    assert fallback(state).action == "play:1"
    state.action_previews = None
    state.drinks[0].text = "次に使用するアクティブスキルカードの効果をもう1回発動"
    assert action_drink_decision(state) is None


def test_score_badges_and_impression_stacks_are_not_added_together(state):
    cash = state.hand[0]
    cash.text = "好印象の150%分パラメータ上昇レッスン中1回"
    cash.tags = parse_tags("", cash.text)
    cash.badge_score = 100
    assert action_drink_decision(state) is None


def test_synthetic_final_turns_and_direct_impression_order(monkeypatch):
    monkeypatch.setenv("HIRO_FALLBACK_DRINKS", "1")
    frozen = json.loads((Path(__file__).parent / "data/synthetic-final-action-drink.json").read_text(encoding="utf-8"))
    states = {}
    for record in frozen["records"]:
        data = dict(record["exam"])
        data["hand"] = [CardView.from_dict(card) for card in data["hand"]]
        data["drinks"] = [DrinkView.from_dict(drink) for drink in data["drinks"]]
        states[record["seq"]] = BattleState(exam="synthetic", turn=record["seq"], max_hp=31, actions_left=1, **data)
    assert action_drink_decision(states[2]) is None
    decision = fallback(states[3])
    assert decision.action == "drink:1" and "8 → 12" in decision.reason
    assert best_direct_impression_action(states[3]) == (0, 8)
