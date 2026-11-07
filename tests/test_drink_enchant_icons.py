"""Drink-status icons remain visual candidates behind their own opt-in."""
from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from hiro.vision import status


@pytest.mark.parametrize("matches,accepted",[
    ([(.808,"tea"),(.483,"coffee")],True),
    ([(.81,"tea"),(.78,"similar_tea")],False),
    ([(.34,"tea"),(.30,"coffee")],False),
    ([(.799,"tea"),(.30,"coffee")],False),
    ([(.8,"tea"),(.65,"coffee")],True),
    ([(.99,"tea")],False),
    ([(.9,"tea"),(.89,"tea"),(.5,"coffee")],True)])
def test_asset_candidates_require_score_and_distinct_asset_separation(monkeypatch,matches,accepted):
    monkeypatch.setattr(status,"_drink_status_libraries",lambda:[NS(size=40,match=lambda _:matches)])
    result=status._drink_enchant_candidate(np.zeros((1280,720,3),np.uint8),1)
    assert bool(result) is accepted
    if accepted:
        assert result["kind"]=="drink_enchant" and result["observed_asset"]=="tea"
        assert result["value"] is result["unit"] is None
        assert "drink_id" not in result and "name" not in result


def setup_unknown_slot(monkeypatch,*,outline=1.,card_score=.5,card=None):
    image=np.zeros((1280,720,3),np.uint8)
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","0")
    monkeypatch.setattr(status,"_icon_index",lambda:({},{}))
    monkeypatch.setattr(status,"match_enchant_card",lambda *_:(card_score,"art"))
    monkeypatch.setattr(status,"_card_from_asset",lambda _:card)
    monkeypatch.setattr(status,"match_status_icon",lambda *_:[(.2,"unknown"),(.1,"other")])
    monkeypatch.setattr(status,"diamond_score",lambda *_:outline)
    monkeypatch.setattr(status,"_value",lambda *_:(None,None))
    return image


@pytest.mark.parametrize("flag,outline,card_score,expected",[(None,1.,.5,False),("1",1.,.5,True),
                                                         ("1",.8,.5,False),("1",1.,.7,False)])
def test_new_switch_and_verified_occupancy_are_required(monkeypatch,flag,outline,card_score,expected):
    image=setup_unknown_slot(monkeypatch,outline=outline,card_score=card_score)
    monkeypatch.delenv("HIRO_WINDOWS_DRINK_ENCHANT_ICONS",raising=False)
    if flag:monkeypatch.setenv("HIRO_WINDOWS_DRINK_ENCHANT_ICONS",flag)
    calls=[]
    monkeypatch.setattr(status,"_drink_enchant_candidate",lambda *a:calls.append(True) or {"kind":"drink_enchant"})
    assert (status._read_slot(image,1)["kind"]=="drink_enchant") is expected
    assert bool(calls) is expected


def test_recognized_card_is_never_overridden(monkeypatch):
    image=setup_unknown_slot(monkeypatch,card_score=.85,card=NS(_id="card",name="source"))
    monkeypatch.setenv("HIRO_WINDOWS_DRINK_ENCHANT_ICONS","1")
    monkeypatch.setattr(status,"_drink_enchant_candidate",lambda *_:pytest.fail("known card"))
    assert status._read_slot(image,1)["card_id"]=="card"


def test_recognized_status_is_never_overridden(monkeypatch):
    image=setup_unknown_slot(monkeypatch)
    image[:]=cv2.cvtColor(np.uint8([[[100,255,255]]]),cv2.COLOR_HSV2BGR)[0,0]
    monkeypatch.setenv("HIRO_WINDOWS_DRINK_ENCHANT_ICONS","1")
    monkeypatch.setattr(status,"match_status_icon",lambda *_:[(.9,"known"),(.1,"other")])
    monkeypatch.setattr(status,"_drink_enchant_candidate",lambda *_:pytest.fail("known status"))
    assert status._read_slot(image,1)["key"]=="known"


def test_missing_library_is_unknown(monkeypatch):
    monkeypatch.setattr(status,"_drink_status_libraries",lambda:[])
    assert status._drink_enchant_candidate(np.zeros((1280,720,3),np.uint8),1) is None


def test_local_drink_positive_and_limited_negative_slots(monkeypatch):
    base=Path(__file__).resolve().parents[1]
    paths=[base/"reports/runs/20261107-080008/frames/00011-exam_card_detail_state_changed.png",
           base/"reports/runs/20261107-082327/frames/00024-exam_card_detail_state_changed.png"]
    if not all(path.exists() for path in paths):pytest.skip("local private evidence absent")
    monkeypatch.setenv("HIRO_WINDOWS_DRINK_ENCHANT_ICONS","1")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    for path in paths:
        image=cv2.imread(str(path))
        row=status._read_slot(image,1)
        assert row["kind"]=="drink_enchant"
        assert row["observed_asset"]=="img_general_pdrink_3-006"
        assert row["identity_status"]=="visual_asset_candidate"
        assert row["value"] is row["unit"] is None
    image=cv2.imread(str(paths[0]))
    for slot in (0,3,4,8,9):
        assert status._drink_enchant_candidate(image,slot) is None
    empty=base/"reports/runs/20261107-082327/frames/00004-exam_enter.jpg"
    assert status._drink_enchant_candidate(cv2.imread(str(empty)),1) is None
