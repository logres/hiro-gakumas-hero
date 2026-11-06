# 来源：digital-hiro src/hiro/vision/ocr.py（develop c3fc27f）
"""Apple Vision OCR（macOS 系统文字识别），用于读固定区域的数字和短文本。

实测在本机比 KAA 的 RapidOCR 快 2–7 倍且更准（见 README）。区域先放大 3 倍再识别，小号描边数字更稳。
"""

import re

import cv2
import Vision
from cv2.typing import MatLike
from Foundation import NSData


def ocr(img: MatLike, *, scale: float = 3.0, languages=("ja-JP", "en-US")) -> list[tuple[str, float]]:
    if scale != 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", img)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(buf.tobytes(), len(buf)), None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)  # accurate
    request.setRecognitionLanguages_(list(languages))
    request.setUsesLanguageCorrection_(False)
    handler.performRequests_error_([request], None)
    out = []
    for obs in request.results() or []:
        cand = obs.topCandidates_(1)[0]
        out.append((str(cand.string()), float(cand.confidence())))
    return out


def ocr_boxes(img: MatLike, *, scale: float = 3.0, languages=("ja-JP", "en-US")) -> list[tuple[str, float, tuple[int, int, int, int]]]:
    """同 ocr()，另给出每段文字在 img 中的外接框 (x1, y1, x2, y2)。"""
    h, w = img.shape[:2]
    if scale != 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", img)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(NSData.dataWithBytes_length_(buf.tobytes(), len(buf)), None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)
    request.setRecognitionLanguages_(list(languages))
    request.setUsesLanguageCorrection_(False)
    handler.performRequests_error_([request], None)
    out = []
    for obs in request.results() or []:
        cand = obs.topCandidates_(1)[0]
        bb = obs.boundingBox()  # 归一化坐标，原点在左下
        x1, y1 = bb.origin.x * w, (1 - bb.origin.y - bb.size.height) * h
        out.append((str(cand.string()), float(cand.confidence()), (round(x1), round(y1), round(x1 + bb.size.width * w), round(y1 + bb.size.height * h))))
    return out


