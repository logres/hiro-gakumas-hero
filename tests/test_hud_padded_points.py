import numpy as np
import pytest
from hiro.vision import pages, digits, action, ocr


@pytest.mark.parametrize("padded,confidence,expected",[("760",.99,760),("760",.5,None),("780",.99,None),("760x",.99,None)])
def test_split_hud_needs_independent_padded_agreement(monkeypatch,padded,confidence,expected):
    monkeypatch.setattr(digits,"read_text",lambda *a:("",True))
    monkeypatch.setattr(digits,"read_dddd",lambda im,box:760 if box==action.POINTS_BOX else None)
    monkeypatch.setattr(action,"read_stamina",lambda im:None)
    monkeypatch.setattr(ocr,"ocr",lambda im,**kw:[("7",.99),("6",.6)] if im.shape[0]==42 else [(padded,confidence)])
    assert pages.read_hud_resources(np.zeros((1280,720,3),np.uint8))["produce_point"]==expected
