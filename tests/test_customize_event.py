import pytest
from hiro.contracts import GameState
from hiro.loop.events import events_from_step, apply_event


def action():
    return {"kind":"CustomizeCard","args":{"menu_session":True,"strict":True,"card_id":"a","upgrade":1,"levels":1,"item_index":0,"price":70}}


def test_verified_menu_customization_marks_exact_owned_version_pending():
    events=events_from_step("SPECIAL_GUIDANCE",action(),True,{},None,seq=3)
    assert len(events)==1 and events[0].kind=="CARD_CUSTOMIZE"
    state=GameState(produce={"deck":[{"card_id":"a","upgrade":0},{"card_id":"a","upgrade":1}],"deck_size":2})
    state,_=apply_event(state,events[0],predictor=lambda *_:[])
    assert not state.produce["deck"][0].get("customized")
    assert state.produce["deck"][1]["customized"] is True
    assert state.produce["deck"][1]["customization_effects_known"] is False
    assert "produce.deck" in state.pending_review
    assert state.produce["deck_size"]==2


@pytest.mark.parametrize("key,value",[("strict",False),("menu_session",False),("upgrade",None),("levels",True),("levels",2)])
def test_legacy_or_unverified_identifiers_do_not_invent_customization(key,value):
    a=action();a["args"][key]=value
    assert events_from_step("SPECIAL_GUIDANCE",a,True,{},None,seq=3)==[]


def test_uncertain_execution_does_not_emit_success_event():
    assert events_from_step("SPECIAL_GUIDANCE",action(),False,{},None,seq=3)==[]
