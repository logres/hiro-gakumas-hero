from hiro.brain.deciders import ProduceDeciders
from hiro.brain.state import CAMPUS_HIRO
from hiro.contracts import GameState


def observed_state(**overrides):
    return GameState(produce=dict(mode='produce-007', step=1, stamina=45,
        max_stamina=45, produce_point=260, params={'Vo':195,'Da':259,'Vi':297},
        growth_permil={'Vo':1343,'Da':1562,'Vi':1558}, star=0, **overrides))


def test_selected_identity_does_not_require_or_invent_specialized_profile():
    state = observed_state()
    deciders = ProduceDeciders(None, idol_card_id='i_card-skin-kllj-3-000', main_attr='Vi')
    result = deciders.produce_state(state)
    assert result.idol_card_id == 'i_card-kllj-3-000'
    assert result.main_attr == 'Vi'
    assert deciders.profile is None and deciders.playbook == []
    assert 'idol_card_id' not in state.produce


def test_observed_identity_and_existing_profile_behavior_preserved():
    assert ProduceDeciders(CAMPUS_HIRO).produce_state(observed_state()).idol_card_id == CAMPUS_HIRO.idol_id
    assert ProduceDeciders(None).produce_state(observed_state()) is None
    result = ProduceDeciders(None, idol_card_id='i_card-kllj-3-000').produce_state(
        observed_state(idol_card_id='i_card-other'))
    assert result.idol_card_id == 'i_card-other'


def test_identity_does_not_fill_unknown_hud():
    state = observed_state()
    del state.produce['stamina']
    assert ProduceDeciders(None, idol_card_id='i_card-kllj-3-000').produce_state(state) is None
