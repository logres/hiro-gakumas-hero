"""Deck identity completeness is independent from stale expected counts."""
import pytest
from hiro.vision.deck import merge_dialog_screens


def cards(count=18):
    return [{"row":i//4,"col":i%4,"card_id":f"card{i}","upgrade":0} for i in range(count)]


def test_unknown_identity_never_claims_complete():
    raw=cards();raw[14].update(card_id=None,upgrade=None)
    result=merge_dialog_screens([raw],expected=17)
    assert result["layout_complete"] is True
    assert result["identities_complete"] is False
    assert result["expected_match"] is False
    assert result["complete"] is False
    assert result["unknown"]==[14]


def test_old_count_disagreement_does_not_overwrite_current_observation():
    result=merge_dialog_screens([cards()],expected=17)
    assert result["layout_complete"] and result["identities_complete"] and result["complete"]
    assert result["expected_match"] is False
    assert len(result["cards"])==18
    assert result["problems"]

@pytest.mark.parametrize("upgrade",[None,True,-1])
def test_unknown_or_invalid_version_is_incomplete(upgrade):
    raw=cards(4);raw[1]["upgrade"]=upgrade
    assert merge_dialog_screens([raw])["complete"] is False


def test_empty_screen_is_not_complete():
    assert merge_dialog_screens([[]])["complete"] is False

@pytest.mark.parametrize("unknown",[True,False])
def test_single_screen_scanner_uses_identity_completeness(monkeypatch,unknown):
    import numpy as np
    from hiro.loop import kaa_patches as kp
    from hiro.vision import deck
    raw=cards(4)
    if unknown: raw[1].update(card_id=None,upgrade=None)
    monkeypatch.setattr(deck,"read_card_dialog",lambda *a:{"cards":raw})
    monkeypatch.setattr(deck,"dialog_scroll",lambda *a:{"scrollable":False,"at_top":True,"thumb":None})
    result=kp.scan_dialog_deck((0,0,720,1280),expected=5,shoot=lambda:np.zeros((1280,720,3),np.uint8))
    assert result["complete"] is (not unknown)
    assert result["expected_match"] is False
    assert result["screens"]==1

@pytest.mark.parametrize("bottom,expected",[(True,True),(False,False),(None,False)])
def test_no_new_rows_needs_actual_scrollbar_bottom(monkeypatch,bottom,expected):
    import numpy as np
    from hiro.loop import kaa_patches as kp
    from hiro.vision import deck
    raw=cards(4)
    monkeypatch.setattr(deck,"read_card_dialog",lambda *a:{"cards":raw})
    calls=[]
    def scroll(*a):
        calls.append(True)
        return {"scrollable":True,"at_top":True,"at_bottom":bottom,"thumb":[0,100]}
    monkeypatch.setattr(deck,"dialog_scroll",scroll)
    result=kp.scan_dialog_deck((0,0,720,1280),shoot=lambda:np.zeros((1280,720,3),np.uint8),swipe=lambda *a:None,sleep=lambda _:None)
    assert result["coverage_complete"] is expected
    assert result["complete"] is expected
