"""Only the bubble heuristic defers dialogs with three card columns."""
import numpy as np
import pytest
from hiro.vision import quick as q, deck


def image(rails=True):
    im=np.zeros((1280,720,3),np.uint8)
    im[960:1120,40:680]=255
    if rails:
        im[650:940,60:75]=255;im[650:940,645:660]=255
    return im

@pytest.mark.parametrize("marks,rails,expected",[
    ([(214,947),(352,946),(491,947)],True,True),
    ([(214,947),(352,946)],True,False),
    ([(214,947),(352,946),(491,947)],False,False),
    ([(100,947),(352,946),(491,947)],True,False),
    ([(214,847),(352,846),(491,847)],True,False),
])
def test_requires_both_panel_and_three_card_columns(monkeypatch,marks,rails,expected):
    import cv2
    monkeypatch.setattr(deck,"_marks",lambda *a:marks)
    im=image(rails)
    assert q._change_candidate_panel(im,cv2.cvtColor(im,cv2.COLOR_BGR2HSV)) is expected

@pytest.mark.parametrize("page",["TRANSITION","DELETE_RESULT","UPGRADE_RESULT"])
@pytest.mark.parametrize("has_cards",[True,False])
def test_actual_bubbles_still_advance_but_card_dialog_never_taps(monkeypatch,page,has_cards):
    from hiro.vision import pitem_select
    monkeypatch.setattr(deck,"is_deck_list",lambda _:False)
    monkeypatch.setattr(pitem_select,"is_select_pitem",lambda _:False)
    monkeypatch.setattr(q,"_hit",lambda _,name:name=="quick_hud_label")
    monkeypatch.setattr(q,"_white_hit",lambda *a:False)
    monkeypatch.setattr(q,"_refresh_dialog",lambda _:None)
    monkeypatch.setattr(q,"_dialog",lambda _:False)
    monkeypatch.setattr(q,"_pitem_note",lambda _:None)
    monkeypatch.setattr(q,"_acquire_bar",lambda _:False)
    monkeypatch.setattr(deck,"_marks",lambda *a:[(214,947),(352,946),(491,947)] if has_cards else [])
    calls=[]
    def bubble(*a): calls.append(True);return page,{"kind":"message"}
    monkeypatch.setattr(q,"read_bubble",bubble)
    result=q.quick_page(image())
    if has_cards:
        assert result is None
        assert not calls
    else:
        assert result["page"]==page and result["tap"]==(12,12)
        assert calls
