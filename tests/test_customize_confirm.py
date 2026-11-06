import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from hiro.vision import customize_confirm as c

pytestmark = pytest.mark.synthetic


def boxes():
    return [(c.TITLE,(60,196,377,231)),("開始時手札に入る",(265,362,455,388)),
            ("70",(349,411,383,434)),("もう怖くないから+",(216,519,457,548)),
            ("760",(242,876,309,911)),("ó90",(497,875,566,914)),
            ("次回以降表示しない",(262,990,479,1017)),
            ("メキャンセル",(113,1143,312,1177)),("実行する",(466,1143,580,1178))]


def read(rows=None, amounts=(760,690)):
    return c.read_confirmation(np.zeros((1280,720,3),np.uint8),rows or boxes(),
        numeric_reader=lambda im,b:70 if b==c.PRICE_BOX else amounts[b==c.AFTER_BOX],
        card_resolver=lambda text:{"card_id":"card", "upgrade":1} if text=="もう怖くないから+" else None)


def test_actual_geometry_and_independent_amounts():
    result=read()
    assert result["price"]==70 and result["p_after"]==690
    assert result["confirm_center"]==(523,1160)
    assert result["suppress_confirmation"] is None


@pytest.mark.parametrize("amounts",[(760,None),(760,90),(760,700),(None,690)])
def test_never_infers_balance(amounts):
    assert read(amounts=amounts) is None


@pytest.mark.parametrize("index",[0,1,2,3,6,7,8])
def test_missing_required_evidence(index):
    rows=boxes();rows.pop(index)
    assert read(rows) is None


def test_wrong_title_and_duplicate_button():
    rows=boxes();rows[0]=(c.TITLE+"?",rows[0][1]);assert read(rows) is None
    rows=boxes();rows.append(rows[-1]);assert read(rows) is None


def test_wrong_region():
    rows=boxes();rows[3]=(rows[3][0],(216,173,457,199))
    assert read(rows) is None


def test_numeric_consensus_requires_both_engines(monkeypatch):
    from hiro.vision import ocr,digits
    image=np.zeros((1280,720,3),np.uint8)
    monkeypatch.setattr(ocr,"ocr",lambda *a,**kw:[("690",1)])
    monkeypatch.setattr(digits,"read_dddd",lambda *a:690)
    assert c.numeric_consensus(image,c.AFTER_BOX)==690
    monkeypatch.setattr(digits,"read_dddd",lambda *a:90)
    assert c.numeric_consensus(image,c.AFTER_BOX) is None
    monkeypatch.setattr(ocr,"ocr",lambda *a,**kw:[("ó90",1)])
    assert c.numeric_consensus(image,c.AFTER_BOX) is None


@pytest.mark.parametrize("name",["confirm","confirm-unchecked"])
def test_private_frames_show_checked_tick(name):
    path=Path(__file__).parents[1]/"reports/windows-probe/customize-review"/(name+".png")
    if not path.exists():pytest.skip("private frame unavailable")
    image=cv2.imread(str(path))
    assert c.checkbox_state(image) is (name=="confirm-unchecked")
    # Both generous balance boxes stay wholly inside the actual gray band.
    for x,y,X,Y in (c.BEFORE_BOX,c.AFTER_BOX):
        assert 54<=x<X<=666 and 846<=y<Y<=942


def test_actual_full_frame_price_misread_is_replaced_by_independent_consensus():
    rows=boxes();rows[2]=("10",rows[2][1])
    assert read(rows)["price"]==70
