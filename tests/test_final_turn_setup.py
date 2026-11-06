"""Regression for r6 seq24: two actions must permit setup before cash-out."""

from hiro.brain.cards import CardView, parse_tags
from hiro.brain.rules import Decision, final_turn_override, violations
from hiro.brain.state import BattleState


def card(slot, name, text, badge=None):
    return CardView(slot, name, f"test-{slot}", 0, True, "mental", 0, 0,
                    None, text, parse_tags(name, text), badge)


def state(actions=2):
    return BattleState(exam="qualify-1", turn=10, remaining_turns=1,
                       hp=20, max_hp=45, genki=20, impression=14,
                       actions_left=actions, hand=[
                           card(0, "cash", "好印象の100%分パラメータ上昇", 315),
                           card(1, "setup", "好印象+5"),
                       ])


def test_two_actions_preserve_setup_decision_and_plan(monkeypatch):
    monkeypatch.setenv("HIRO_FINAL_TURN_SETUP", "1")
    current = state()
    choice = Decision("play:1", "先叠好印象再兑现", "llm",
                      plan=[{"action": "play", "card": "cash"}])
    assert violations(current, choice) == []
    assert final_turn_override(current, choice) is None
    assert choice.plan == [{"action": "play", "card": "cash"}]


def test_last_action_still_requires_cashout(monkeypatch):
    monkeypatch.setenv("HIRO_FINAL_TURN_SETUP", "1")
    choice = Decision("play:1", "setup", "llm")
    assert final_turn_override(state(1), choice).action == "play:0"


def test_skip_still_cashes_out_with_two_actions(monkeypatch):
    monkeypatch.setenv("HIRO_FINAL_TURN_SETUP", "1")
    assert final_turn_override(state(), Decision("skip", "skip", "llm")).action == "play:0"


def test_opt_in_keeps_legacy_default(monkeypatch):
    monkeypatch.delenv("HIRO_FINAL_TURN_SETUP", raising=False)
    assert final_turn_override(state(), Decision("play:1", "setup", "llm")).action == "play:0"
