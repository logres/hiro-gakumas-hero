"""OCR case variants and incomplete lesson identity must not become blind actions."""
import numpy as np
import pytest
from hiro.vision import action
from hiro.brain.deciders import ProduceDeciders
from hiro.contracts import GameState, ActionKind

@pytest.mark.parametrize('label,attr', [('VI公開レッスン','vi'), ('VO.公開レッスン','vo'), ('da公開レッスン','da')])
def test_lesson_attr_ignores_ocr_case(monkeypatch,label,attr):
    monkeypatch.setattr(action,'ocr_boxes',lambda *a,**k:[(label,1.0,(460,240,620,265))])
    rows=action._options(np.zeros((1280,720,3),np.uint8))
    assert len(rows)==1 and rows[0].kind=='open_lesson' and rows[0].attr==attr

def test_unknown_generic_lesson_makes_screen_incomplete():
    s=action.ActionSelectState('exam',2,39,45,370,{'vo':200,'da':200,'vi':200},{},{},75,None,
        [action.ActionOption('lesson','?公開レッスン',None,(540,1020))])
    assert not s.complete

def test_unknown_lesson_attr_waits_without_preview_or_model(monkeypatch):
    d=ProduceDeciders(None)
    monkeypatch.setattr(d,'produce_state',lambda s:None)
    s=GameState(page_fields={'options':[{'option':'training','attr':None,'hp_cost':8}]})
    result=d.decide('ACTION_SELECT',s)
    assert result.action.kind is ActionKind.WAIT
    assert '属性' in result.reason
