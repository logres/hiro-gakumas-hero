"""Legacy empirical constraints must not silently become cross-route rules."""

import pytest

from hiro.brain.cards import CardView, DrinkView
from hiro.brain.state import BattleState
from hiro.brain.rules import Decision, violations
from hiro.produce.exam_policy import expert_pick, llm_blocks


def state(effect=None):
    return BattleState(
        "qualify-2", 6, 7, 30, 45, 10,
        [CardView(0, "synthetic", "synthetic-card", 0, True, "mental", 0, 0, None, "元気+5")],
        drinks=[DrinkView(0, "ブーストエキス", None, "パラメータ上昇量増加30%（3ターン）体力消費2")],
        motivation=15, impression=66, actions_left=1, recommended_effect=effect,
    )


@pytest.mark.parametrize("effect", [None, "ProduceExamEffectType_ExamReview", "ProduceExamEffectType_ExamConcentration"])
def test_explicit_other_or_unknown_route_does_not_inherit_boost_hold(monkeypatch, effect):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    assert llm_blocks(state(effect), "drink:0") is None


def test_verified_yaruki_keeps_existing_empirical_constraint(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    assert "R3" in llm_blocks(state("ProduceExamEffectType_ExamCardPlayAggressive"), "drink:0")


def test_legacy_mode_keeps_constraint(monkeypatch):
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    assert "R3" in llm_blocks(state(), "drink:0")


def test_other_route_previews_rank_only_current_legal_actions(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    current = state("ProduceExamEffectType_ExamReview")
    current.action_previews = [{"legal_action": "play:99", "期望终局分": 9000},
                              {"legal_action": "drink:0", "期望终局分": 500},
                              {"legal_action": "play:0", "期望终局分": 100}]
    choice = expert_pick(current)
    assert choice.decision.action == "drink:0" and choice.gap == 400
    assert choice.hard_rules == []


def test_final_turn_playable_setup_is_not_proof_that_skipping_loses_score(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    current = state("ProduceExamEffectType_ExamReview")
    current.remaining_turns = 1
    current.drinks = []
    current.hand = [CardView(0, "synthetic-setup", "setup", 0, True, "mental", 0, 0,
                             {"type": "ExamCostType_ExamReview", "value": 1}, "好印象消費1やる気+5")]
    assert violations(current, Decision("skip", "No remaining payoff", "llm")) == []
    current.recommended_effect = "ProduceExamEffectType_ExamCardPlayAggressive"
    assert any("最後" in reason or "最后" in reason for reason in violations(current, Decision("skip", "legacy", "llm")))
