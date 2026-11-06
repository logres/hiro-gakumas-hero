import cv2
import numpy as np
import pytest

from hiro.vision import shop


@pytest.mark.parametrize("digits,texts,expected", [
    (92, ["92", "92"], 92), (77, ["77", "17"], None),
    (75, ["15", "15"], None), (52, ["1552", "1552"], None),
    (None, ["52", "52"], None), (35, ["", "35"], None),
    (35, ["3 5", "35"], None),
])
def test_price_requires_independent_numeric_read_and_both_scales_to_agree(monkeypatch, digits, texts, expected):
    image = np.full((80, 100, 3), 255, dtype=np.uint8)
    cv2.putText(image, "92", (13, 45), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 2)
    monkeypatch.setattr(shop, "read_dddd", lambda img, box: digits)
    calls = []

    def ocr(prepared, *, scale, languages):
        calls.append(scale)
        assert languages == ("en-US",)
        assert (prepared[:12] == 255).all() and (prepared[:, :12] == 255).all()
        assert set(np.unique(prepared)).issubset({0, 255})
        text = texts[0 if scale == 2 else 1]
        return [(text, .99)] if text else []

    monkeypatch.setattr(shop, "ocr", ocr)
    assert shop._verified_price(image, (10, 15, 70, 55)) == expected
    assert calls[0] == 2 and all(scale in (2, 4) for scale in calls)


def test_low_confidence_is_unknown_not_a_majority_vote(monkeypatch):
    monkeypatch.setattr(shop, "read_dddd", lambda *a: 75)
    monkeypatch.setattr(shop, "ocr", lambda *a, **k: [("75", .89)])
    assert shop._verified_price(np.full((40, 80, 3), 255, np.uint8), (0, 0, 60, 30)) is None


def test_sale_and_ordinary_prices_use_separate_numeric_regions(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_SHOP_PRICE_VERIFY", "1")
    image = np.full((1280, 720, 3), 255, np.uint8)
    # Synthetic SALE pill, without relying on OCR recognizing its letters.
    image[600:620, 95:155] = (130, 30, 240)
    monkeypatch.setattr(shop, "ocr_boxes", lambda *a, **k: [
        ("強化や削除", .99, (80, 410, 500, 440)),
        ("7", .99, (380, 155, 390, 170)), ("7", .99, (392, 155, 402, 170))])
    monkeypatch.setattr(shop, "_card", lambda *a: {"kind": "card", "card_id": "synthetic-card"})
    monkeypatch.setattr(shop, "_drink", lambda *a: {"kind": "drink", "drink_id": "synthetic-drink"})
    boxes = []
    monkeypatch.setattr(shop, "_verified_price", lambda img, box: boxes.append(box) or 92)
    result = shop.read_consult(image)
    assert result["shelf"][0]["sale"] is True
    assert boxes[0] == (65 + 76, 622, 65 + 115, 648)  # excludes crossed-out old price
    assert result["shelf"][2]["sale"] is False  # split digits are not a SALE indicator
    assert boxes[2] == (375 + 50, 622, 375 + 115, 648)


def test_default_off_does_not_change_legacy_price_reader(monkeypatch):
    monkeypatch.delenv("HIRO_WINDOWS_SHOP_PRICE_VERIFY", raising=False)
    monkeypatch.setattr(shop, "ocr_boxes", lambda *a, **k: [])
    monkeypatch.setattr(shop, "_card", lambda *a: {"kind": "card", "card_id": "synthetic"})
    monkeypatch.setattr(shop, "_drink", lambda *a: {"kind": "drink", "drink_id": "synthetic"})
    monkeypatch.setattr(shop, "_verified_price", lambda *a: pytest.fail("Default-off must preserve old reader"))
    result = shop.read_consult(np.full((1280, 720, 3), 255, np.uint8))
    assert all(item["price"] is None for item in result["shelf"])
