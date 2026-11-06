import numpy as np
import pytest

from hiro.platforms.windows import ocr


def test_scaled_quad_is_clamped_to_original_image(monkeypatch):
    seen = []
    def engine(language):
        seen.append(language)
        def recognize(image):
            assert image.shape == (30, 60, 3)
            return [[[[63, 27], [-3, 3], [30, 33], [0, 0]], '文字', 0.875]], None
        return recognize
    monkeypatch.setattr(ocr, '_engine', engine)
    assert ocr.ocr_boxes(np.zeros((10, 20, 3), np.uint8)) == [('文字', 0.875, (0, 0, 20, 10))]
    assert seen == ['japan']


def test_empty_and_english_selection(monkeypatch):
    seen = []
    def engine(language):
        seen.append(language)
        return lambda image: (None, None)
    monkeypatch.setattr(ocr, '_engine', engine)
    assert ocr.ocr(np.zeros((10, 20, 3), np.uint8), languages=('en-US',), scale=1) == []
    assert seen == ['en']


def test_text_projection_preserves_confidence(monkeypatch):
    monkeypatch.setattr(ocr, 'ocr_boxes', lambda *args, **kwargs: [('123', 0.93, (1, 2, 3, 4))])
    assert ocr.ocr(None) == [('123', 0.93)]


@pytest.mark.parametrize('languages', [(), ('zh-CN',), ('ja-JP', 'fr-FR')])
def test_unsupported_languages(languages):
    with pytest.raises(ValueError, match='Unsupported OCR languages'):
        ocr.ocr_boxes(np.zeros((10, 20, 3), np.uint8), languages=languages)


@pytest.mark.parametrize('scale', [0, -1, float('nan'), float('inf')])
def test_invalid_scale(scale):
    with pytest.raises(ValueError, match='scale'):
        ocr.ocr_boxes(np.zeros((10, 20, 3), np.uint8), scale=scale)
