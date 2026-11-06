import pytest

from hiro.brain.cards import CardView, parse_tags
from hiro.brain.state import BattleState


@pytest.mark.parametrize("remaining", [None, 0, 1])
def test_generic_budget_preserves_unknown_and_does_not_certify_refund(remaining, monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    text = "スキルカード使用数追加+1"
    refund = CardView(0, "refund", "any-idol-card", 1, True, "mental", 0, 0, None,
                      text, parse_tags("refund", text))
    direct = CardView(1, "direct", "direct-card", 0, True, "active", 0, 0, None, "パラメータ+10")
    state = BattleState("qualify-3", 3, 10, 30, 45, 0, [refund, direct], actions_left=remaining)
    budget = state.to_prompt_dict()["action_budget"]
    assert budget["estimated_actions_left"] is remaining
    assert budget["returns_actions_after_play"] == ["refund"]
    assert budget["consumes_action_without_known_refund"] == ["direct"]
    assert "not verification of customized effects" in budget["basis"]
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE")
    assert state.action_budget()["不耗行动的牌"] == ["refund"]
