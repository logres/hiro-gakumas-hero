import pytest

from hiro.brain.state import BattleState, ExamMemory


@pytest.mark.parametrize("observed", [None, 0, 1])
def test_generic_trigger_count_requires_equipment_bound_observation(monkeypatch, observed):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    memory = ExamMemory("qualify-3", item_charges_left=1)
    state = BattleState.build(memory, None, remaining_turns=3, hp=26, genki=23,
                              hand=[], pitem_charges=observed)
    assert state.item_charges_left is None
    assert state.pitem_charges is None
    assert memory.item_charges_left == 1  # No anonymous badge overwrites history.
    assert "item_charges_left" not in state.to_prompt_dict()
    assert "pitem_charges" not in state.to_prompt_dict()


def test_legacy_mode_retains_existing_counter(monkeypatch):
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    memory = ExamMemory("qualify-3", item_charges_left=1)
    state = BattleState.build(memory, None, remaining_turns=3, hp=26, genki=23, hand=[])
    assert state.item_charges_left == 1
