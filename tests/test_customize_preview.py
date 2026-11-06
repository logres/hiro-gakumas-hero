import numpy as np
import pytest
from hiro.produce.customize_preview import collect_current_menu


def harness(*, no_effect=False, spend=False):
    state = {"selected":None, "taps":[], "p":760}
    def shoot():
        return np.zeros((1280,720,3),dtype=np.uint8)
    def read(_):
        return {"view":"menu", "selected_card":{"card_id":"a","upgrade":1},
                "produce_point":state["p"], "menu":{"total_left":1,"selected_item_index":state["selected"],
                "items":[{"item_index":i,"price":p,"left":1,"available":True,
                          "selected":state["selected"]==i,"center":[x,845]}
                         for i,p,x in ((0,70,143),(1,100,364))]}}
    def click(x,y):
        state["taps"].append((x,y))
        if not no_effect: state["selected"]={143:0,364:1}[x]
        if spend: state["p"]-=70
    return state, dict(shoot=shoot,read=read,click=click,wait=lambda _:None)


def test_collects_each_actual_option_without_execution_clicks():
    state, args=harness()
    result=collect_current_menu(**args)
    assert len(result)==2
    assert state["taps"]==[(143,845),(364,845)]
    assert state["p"]==760
    assert all(r.image.shape==(1280,720,3) for r in result)


def test_failed_selection_is_not_retried():
    state,args=harness(no_effect=True)
    with pytest.raises(ValueError,match="未确认选中"):
        collect_current_menu(**args)
    assert state["taps"]==[(143,845)]


def test_balance_change_aborts_review():
    state,args=harness(spend=True)
    with pytest.raises(ValueError,match="余额"):
        collect_current_menu(**args)
    assert len(state["taps"])==1
