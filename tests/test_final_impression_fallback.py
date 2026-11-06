from dataclasses import replace

from hiro.brain.cards import CardView, parse_tags
from hiro.brain.rules import fallback
from hiro.brain.state import BattleState


def test_after_action_drink_does_not_revert_to_cheapest_small_gain(monkeypatch):
    monkeypatch.setenv("HIRO_FALLBACK_DRINKS", "1")
    def card(slot, gain, cost):
        text = f"好印象+{gain}レッスン中1回"
        return CardView(slot, f"setup-{slot}", f"test-{slot}", 0, True, "mental",
                        cost, 0, None, text, parse_tags("", text))
    large, small = card(0, 9, 7), card(1, 2, 1)
    current = BattleState("qualify-1", 10, 1, 30, 40, 20, [large, small],
                          actions_left=2, impression=21)
    assert fallback(current).action == "play:0"
    observed_after = replace(current, hand=[small], genki=13, impression=30, actions_left=1)
    assert fallback(observed_after).action == "play:1"
    # Default route remains unchanged until the controlled rollout is enabled.
    monkeypatch.delenv("HIRO_FALLBACK_DRINKS")
    assert fallback(current).action == "play:1"
