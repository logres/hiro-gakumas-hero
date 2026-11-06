"""Unknown image IDs may only be filled by independent selected detail evidence."""
import numpy as np
import pytest
from hiro.vision import deck, ocr

@pytest.mark.parametrize("cursor,detail,original,expected",[
    (True,True,None,"verified"),(False,True,None,None),(True,False,None,None),
    (True,True,"different","different")])
def test_selected_detail_only_fills_unknown_cell(monkeypatch,cursor,detail,original,expected):
    raw=[{"index":0,"row":0,"col":0,"card_id":original,"upgrade":None,"rect":(80,700,118,118)}]
    monkeypatch.setattr(deck,"read_card_grid",lambda *a:raw)
    monkeypatch.setattr(deck,"_cursor_px",lambda *a:1000 if cursor else 0)
    monkeypatch.setattr(ocr,"ocr_boxes",lambda *a,**k:[("ExactName+",.99,(0,0,100,20))] if detail else [])
    monkeypatch.setattr(deck,"card_from_name",lambda *a:{"card_id":"verified","name":"ExactName","upgrade":1})
    result=deck.read_card_dialog(np.zeros((1280,720,3),np.uint8))
    assert result["cards"][0]["card_id"]==expected
    if expected=="verified":
        assert result["cards"][0]["upgrade"]==1
        assert result["cards"][0]["identity_basis"]=="selected_cursor_and_exact_detail_name"
    elif original:
        assert result["selected_card"] is None

@pytest.mark.parametrize("found,upgrade",[(True,0),(False,0),(True,None)])
def test_incoming_read_requires_current_image_and_known_version(monkeypatch,found,upgrade):
    from kaa.game_ui import skill_card_select
    from types import SimpleNamespace
    monkeypatch.setattr(skill_card_select,"match_card_region",lambda _:SimpleNamespace(_id="new",name="New") if found else None)
    monkeypatch.setattr(deck,"_plus",lambda _:upgrade)
    result=deck.read_change_incoming(np.zeros((1280,720,3),np.uint8))
    if found and upgrade is not None:
        assert result["card_id"]=="new" and result["source"]=="screen"
    else: assert result is None
