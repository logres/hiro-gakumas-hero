"""Windows multiplier recovery needs explicit percent, same attribute, and dddd vote."""
import numpy as np
import pytest
from hiro.vision import hif


@pytest.mark.parametrize("secondary,expected",[("ボーカル1391％.",1391),("ダンス1391%",None),("ボーカル13918.",None)])
def test_scale_two_requires_same_attribute_and_explicit_percent(monkeypatch,secondary,expected):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    calls=[]
    monkeypatch.setattr(hif,"ocr",lambda crop,scale: calls.append(scale) or [(secondary,.99)])
    result=hif._parsed_attr_with_scale_fallback(np.zeros((1280,720,3),np.uint8),"ボーカル13918.",None)
    assert result == {"attr":"vocal","multiplier_pct":expected}
    assert calls == [2.0]


def test_fallback_retains_independent_vote_conflict(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setattr(hif,"ocr",lambda *a,**kw:[("ボーカル1391%",.99)])
    monkeypatch.setattr(hif,"read_dddd",lambda *a:1397)
    monkeypatch.setattr(hif,"_MULT_SEEN",{})
    img=np.zeros((1280,720,3),np.uint8)
    result=hif._parsed_attr_with_scale_fallback(img,"ボーカル13918.",None)
    assert hif._vote_multiplier(img,result["multiplier_pct"],None,result["attr"]) == (None,[1391,1397])


@pytest.mark.parametrize("enabled,text",[(False,"ボーカル13918."),(True,"ボーカル1391%"),(True,"13918.")])
def test_no_extra_ocr_when_disabled_valid_or_unknown_attribute(monkeypatch,enabled,text):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1" if enabled else "0")
    monkeypatch.setattr(hif,"ocr",lambda *a,**kw: pytest.fail("unexpected secondary OCR"))
    assert hif._parsed_attr_with_scale_fallback(np.zeros((1280,720,3),np.uint8),text,None) == hif._parse_attr(text)
