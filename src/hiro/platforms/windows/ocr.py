"""Offline Windows OCR using the Japanese/English models shipped with ksaa-res."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path


def _language(languages) -> str:
    requested = {str(lang).lower().replace('_', '-') for lang in languages}
    supported = {'ja', 'ja-jp', 'en', 'en-us', 'en-gb'}
    if not requested or requested - supported:
        raise ValueError(f'Unsupported OCR languages: {sorted(requested)}; supported: Japanese and English')
    return 'japan' if requested & {'ja', 'ja-jp'} else 'en'


@lru_cache(maxsize=2)
def _engine(language: str):
    from hiro.platforms import PlatformUnavailableError
    try:
        from kotonebot.util import lf_path
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise PlatformUnavailableError('Windows OCR requires the play dependencies (kotonebot, ksaa-res, RapidOCR).') from exc
    model = Path(lf_path(f'models/{language}_PP-OCRv3_rec_infer.onnx'))
    if not model.is_file():
        raise PlatformUnavailableError(f'Bundled OCR model is missing: {model}')
    return RapidOCR(
        rec_model_path=str(model), use_det=True, use_cls=False, use_rec=True,
        intra_op_num_threads=2, inter_op_num_threads=1,
    )


def ocr(img, *, scale: float = 3.0, languages=('ja-JP', 'en-US')) -> list[tuple[str, float]]:
    return [(text, confidence) for text, confidence, _ in ocr_boxes(img, scale=scale, languages=languages)]


def recognize_line(img, *, languages=('ja-JP', 'en-US')) -> list[tuple[str, float]]:
    """Recognize one already-cropped BGR line, without detection or boxes.

    Confidence is returned unfiltered. Callers must verify single-line geometry,
    grammar and confidence; this does not provide spatial detection evidence.
    """
    if (getattr(img,'ndim',None) != 3 or img.shape[2] != 3
            or not img.shape[0] or not img.shape[1]):
        raise ValueError('recognize_line requires a nonempty BGR image')
    language = _language(languages)
    results, _ = _engine(language)(img,use_det=False,use_cls=False,use_rec=True)
    output = []
    for row in results or []:
        if not isinstance(row,(tuple,list)) or len(row) != 2 or not isinstance(row[0],str):
            raise ValueError('recognize_line received malformed recognition-only output')
        confidence = float(row[1])
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError('recognize_line received invalid confidence')
        output.append((row[0],confidence))
    return output


def _reading_order(items):
    """Horizontal UI text: rows top-to-bottom, fragments left-to-right.

    Detection tops differ slightly between kanji and digits. Group by vertical
    overlap with a fixed row anchor instead of sorting every fragment by y.
    Keep boxes and confidence unchanged; this is not a column/document parser.
    """
    rows = []
    for item in sorted(items, key=lambda item: (item[2][1], item[2][0])):
        _, y1, _, y2 = item[2]
        if rows:
            anchor = rows[-1][0][2]
            overlap = min(y2, anchor[3]) - max(y1, anchor[1])
            height = min(y2 - y1, anchor[3] - anchor[1])
            if height > 0 and overlap >= height * 0.5:
                rows[-1].append(item)
                continue
        rows.append([item])
    return [item for row in rows for item in sorted(row, key=lambda item: item[2][0])]


def ocr_boxes(img, *, scale: float = 3.0, languages=('ja-JP', 'en-US')) -> list[tuple[str, float, tuple[int, int, int, int]]]:
    """Recognize BGR input, returning boxes in original top-left image pixels."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('OCR scale must be finite and positive')
    language = _language(languages)
    h, w = img.shape[:2]
    if not h or not w:
        raise ValueError('OCR image must not be empty')
    if scale != 1:
        import cv2
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    scaled_h, scaled_w = img.shape[:2]
    results, _ = _engine(language)(img)
    output = []
    for quad, text, confidence in results or []:
        xs = [float(point[0]) * w / scaled_w for point in quad]
        ys = [float(point[1]) * h / scaled_h for point in quad]
        box = (
            max(0, min(w, round(min(xs)))), max(0, min(h, round(min(ys)))),
            max(0, min(w, round(max(xs)))), max(0, min(h, round(max(ys)))),
        )
        output.append((str(text), float(confidence), box))
    return _reading_order(output)
