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


def test_reading_order_with_digit_baseline_offset(monkeypatch):
    # Reproduces a real engine output: kanji, rightmost fragment, then digits.
    fragments = [('体力', (10, 10, 50, 35)), ('テスト456', (110, 11, 200, 35)),
                 ('123', (60, 14, 100, 34)), ('次の行', (10, 50, 90, 75))]
    results = [([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], text, .9)
               for text, (x1,y1,x2,y2) in fragments]
    monkeypatch.setattr(ocr, '_engine', lambda language: lambda image: (results, None))
    boxes = ocr.ocr_boxes(np.zeros((100, 220, 3), np.uint8), scale=1)
    assert [item[0] for item in boxes] == ['体力', '123', 'テスト456', '次の行']
    assert boxes[1] == ('123', .9, (60, 14, 100, 34))
