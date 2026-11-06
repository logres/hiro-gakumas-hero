from hiro.brain.state import BattleState


def test_generic_prompt_preserves_known_multipliers_without_inventing_order(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    state = BattleState("qualify-3", 10, 3, 26, 45, 7, [],
                        attr="Vo", multiplier_permil=13910,
                        attr_permils={"Vi": 28680, "Da": 17190, "Vo": 13910})
    prompt = state.to_prompt_dict()
    assert prompt["known_attribute_multiplier_permils"] == state.attr_permils
    assert prompt["turn_multiplier"] == "13.91×"
    assert state.trend is None and state.final_turn_permil is None
    assert "不提供未来回合顺序" in prompt["known_attribute_multiplier_note"]
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE")
    assert "known_attribute_multiplier_permils" not in state.to_prompt_dict()


def test_unknown_attributes_are_not_replaced_by_zero_or_another_attribute(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    state = BattleState("qualify-3", 1, 12, 30, 45, 0, [],
                        attr_permils={"Vo": None, "Da": 0, "Vi": 28680})
    assert state.to_prompt_dict()["known_attribute_multiplier_permils"] == {"Vi": 28680}
    state.attr_permils = {}
    assert "known_attribute_multiplier_permils" not in state.to_prompt_dict()
