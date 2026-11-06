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
    return output
