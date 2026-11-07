"""Optional single-line recognition has no boxes and cannot override glyphs."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from hiro.platforms.windows import ocr as windows
from hiro.vision import ocr as vision
from hiro.vision import status
from hiro.platforms import PlatformUnavailableError


def test_provider_uses_cached_engine_recognition_only_and_preserves_confidence(monkeypatch):
    image=np.zeros((36,116,3),np.uint8)
    seen=[]
    def engine(language):
        def recognize(img,**flags):
            seen.append((language,img,flags))
            return [["20％",.8]], [.01]
        return recognize
    monkeypatch.setattr(windows,"_engine",engine)
    assert windows.recognize_line(image)==[("20％",.8)]
    assert seen[0][0]=="japan" and seen[0][1] is image
    assert seen[0][2]=={"use_det":False,"use_cls":False,"use_rec":True}


@pytest.mark.parametrize("image",[None,np.zeros((20,30),np.uint8),np.zeros((20,30,4),np.uint8),
                                  np.zeros((0,30,3),np.uint8)])
def test_line_provider_rejects_invalid_shape_before_model_call(monkeypatch,image):
    monkeypatch.setattr(windows,"_engine",lambda *_:pytest.fail("invalid shape"))
    with pytest.raises(ValueError,match="BGR"):windows.recognize_line(image)


@pytest.mark.parametrize("rows",[[[[],"text",.99]],[["x",float('nan')]],[["x",1.2]]])
def test_line_provider_rejects_wrong_return_shape_or_confidence(monkeypatch,rows):
    monkeypatch.setattr(windows,"_engine",lambda _:lambda *a,**kw:(rows,None))
    with pytest.raises(ValueError):windows.recognize_line(np.zeros((20,30,3),np.uint8))


def test_line_provider_empty_results_are_not_a_fabricated_number(monkeypatch):
    monkeypatch.setattr(windows,"_engine",lambda _:lambda *a,**kw:(None,None))
    assert windows.recognize_line(np.zeros((20,30,3),np.uint8))==[]


def test_neutral_interface_requires_optional_capability_without_fabricating_boxes(monkeypatch):
    monkeypatch.setattr(vision,"get_backend",lambda _:NS())
    with pytest.raises(PlatformUnavailableError):vision.recognize_line(np.zeros((20,30,3),np.uint8))
    monkeypatch.setattr(vision,"get_backend",lambda _:NS(recognize_line=lambda img,**kw:[("5",.99)]))
    assert vision.recognize_line(np.zeros((20,30,3),np.uint8))==[("5",.99)]


@pytest.mark.parametrize("lines,glyph,accepted",[
    ([("20％",.99)],20,True), ([("20％",.89)],20,False),
    ([("2",.99),("0％",.99)],20,False), ([("57",.99)],5,False),
    ([("3ターン",.99)],3,False), ([],20,False), ([("20%3",.99)],20,False)])
def test_status_line_path_requires_one_complete_confident_glyph_agreement(monkeypatch,lines,glyph,accepted):
    monkeypatch.setenv("HIRO_WINDOWS_LINE_OCR","1")
    monkeypatch.setattr(status,"read_dddd",lambda *_:209)
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:glyph)
    calls=[]
    monkeypatch.setattr(status,"recognize_line",lambda image:calls.append(image.shape) or lines)
    detector=[]
    monkeypatch.setattr(status,"ocr",lambda *a,**kw:detector.append(True) or [])
    result=status._verified_status_number(np.zeros((1280,720,3),np.uint8),5)
    assert result==(glyph if accepted else None)
    assert calls==[(36,116,3)]
    assert bool(detector) is not accepted


@pytest.mark.parametrize("enabled,glyph",[(False,20),(True,None)])
def test_flag_off_or_unknown_glyph_keeps_established_detector_path(monkeypatch,enabled,glyph):
    monkeypatch.setenv("HIRO_WINDOWS_LINE_OCR","1" if enabled else "0")
    monkeypatch.setattr(status,"read_dddd",lambda *_:209)
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:glyph)
    monkeypatch.setattr(status,"recognize_line",lambda *_:pytest.fail("not eligible"))
    monkeypatch.setattr(status,"ocr",lambda *a,**kw:[])
    assert status._verified_status_number(np.zeros((1280,720,3),np.uint8),5) is None


def test_unsupported_line_capability_falls_back_without_changing_detector_result(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_LINE_OCR","1")
    monkeypatch.setattr(status,"read_dddd",lambda *_:209)
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:20)
    def unavailable(*_):raise PlatformUnavailableError("no line capability")
    monkeypatch.setattr(status,"recognize_line",unavailable)
    monkeypatch.setattr(status,"ocr",lambda *a,**kw:[("20％",.99)])
    assert status._verified_status_number(np.zeros((1280,720,3),np.uint8),5)==20


def test_local_frozen_eight_rois_preserve_strict_acceptance(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    report=root/"reports/windows-probe/r31-line-ocr-comparison.json"
    if not report.exists():pytest.skip("private frozen comparison absent")
    data=json.loads(report.read_text(encoding="utf8"))
    for row in data["rois"]:
        image=cv2.imread(str(root/row["source"]))
        if hashlib.sha256(image.tobytes()).hexdigest()!=row["image_pixel_sha256"]:
            pytest.skip("frozen source image changed")
        x,y,a,b=row["roi_xyxy"]
        lines=windows.recognize_line(image[y:b,x:a])
        accepted=False
        if len(lines)==1:
            text,confidence=lines[0]
            import re
            match=re.fullmatch(r"([0-9]+)[%％]?",text.strip())
            accepted=confidence>=.9 and match is not None and int(match[1])==row["independent_digit_glyph"]
        assert accepted is (row["truth_kind"]=="percent")


def test_local_detector_missed_percent_baselines_recover_with_line_flag(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    paths=[root/f"reports/runs/20261107-084940/frames/{i:05d}-exam_card_detail_baseline.png" for i in (6,9)]
    if not all(path.exists() for path in paths):pytest.skip("private baseline evidence absent")
    monkeypatch.setenv("HIRO_WINDOWS_LINE_OCR","1")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    for path in paths:
        assert status._value(cv2.imread(str(path)),5,"status")[0]==20
