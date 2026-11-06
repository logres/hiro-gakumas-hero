"""Selected event recovery needs a full title and independent row/detail evidence."""
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from hiro.vision import scene, event, ocr


def fields():
    return {"complete": True, "selected": 2, "effect": "ボーカル上昇+150", "choices": [
        {"index": i, "text": "選択肢"+str(i), "selected": i==2, "center": [360,y]}
        for i,y in enumerate(event.ROW_Y)]}

@pytest.mark.parametrize("title,expected",[("授業","STUDY"),("おでかけ","OUTING"),("授","unknown"),("授業を選択","unknown"),("", "unknown")])
def test_exact_title_and_layout(monkeypatch,title,expected):
    monkeypatch.setattr(ocr,"ocr_boxes",lambda *a,**k:[(title,.99,(0,0,40,20))])
    monkeypatch.setattr(event,"read_event_choices",lambda _:fields())
    assert scene._selected_event(np.zeros((1280,720,3),dtype=np.uint8)) == (None if expected=="unknown" else expected)

@pytest.mark.parametrize("fault",["missing_row","no_selection","no_detail","wrong_rows","incomplete","ambiguous_selection","short_text"])
def test_title_alone_never_classifies(monkeypatch,fault):
    data=fields()
    if fault=="missing_row": data["choices"].pop()
    elif fault=="no_selection": data["selected"]=None
    elif fault=="no_detail": data["effect"]=None
    elif fault=="wrong_rows": data["choices"][0]["center"]=[360,500]
    elif fault=="incomplete": data["complete"]=False
    elif fault=="ambiguous_selection": data["choices"][0]["selected"]=True
    else: data["choices"][0]["text"]="授"
    monkeypatch.setattr(ocr,"ocr_boxes",lambda *a,**k:[("授業",.99,(0,0,40,20))])
    monkeypatch.setattr(event,"read_event_choices",lambda _:data)
    assert scene._selected_event(np.zeros((1280,720,3),dtype=np.uint8)) is None

@pytest.mark.parametrize("name",["STUDY","OUTING"])
def test_idle_controller_dispatches_recovered_events(monkeypatch,name):
    from hiro.loop.controller import HiroController, Scene, SceneType
    monkeypatch.setattr(scene,"classify_current",lambda:SimpleNamespace(scene=name))
    monkeypatch.setattr(HiroController,"session",None)
    result=HiroController._reclassify_idle(SimpleNamespace(),Scene(SceneType.IDLE))
    assert result.type is getattr(SceneType,name)

@pytest.mark.parametrize("path",["reports/windows-probe/study-day17/03.png","traces/windows-qualify-04-r7/frames/00040.jpg"])
def test_local_real_selected_study_frames(monkeypatch,path):
    # Local untracked evidence is optional; no screenshot is copied into tests.
    import cv2
    path = Path(__file__).resolve().parents[1] / path
    if not path.is_file(): pytest.skip("local day17 evidence absent")
    from hiro.platforms import reset
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    reset()
    image=cv2.imread(str(path))
    assert scene._selected_event(image)=="STUDY"
    # Same title with choices/detail physically removed must remain unknown.
    image[445:950,:,:]=0
    assert scene._selected_event(image) is None
