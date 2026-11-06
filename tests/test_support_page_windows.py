"""Strict support counter reading, independent of editable names/Japanese OCR."""
import numpy as np
import pytest

from hiro.vision import ocr
from hiro.vision import support_screens as screens


@pytest.mark.parametrize("text, expected", [("7/20", (7, 20)), ("20 / 20", (20, 20)),
    ("0/20", None), ("21/20", None), ("7", None), ("7/2", None), ("7/20x", None),
    ("17/200", None), ("07/20", None), ("1/20 7/20", None)])
def test_strict_fraction(monkeypatch, text, expected):
    def recognize(img, **kwargs):
        assert kwargs["languages"] == ("en-US",)
        assert img.shape == (64, 87, 3)  # Dedicated crop plus numeric preprocessing border.
        return [(text, .99)]
    monkeypatch.setattr(ocr, "ocr", recognize)
    assert screens.step2_page(np.zeros((1280, 720, 3), np.uint8)) == expected


def test_step2_ignores_incorrect_fullscreen_counter_and_name(monkeypatch):
    monkeypatch.setattr(ocr, "ocr", lambda *a, **k: [("7/20", .99)])
    monkeypatch.setattr(screens, "read_tile", lambda *a, **k: {})
    boxes = [("サポート選択", (10, 20, 200, 60)),
             ("サポートカード編成1", (200, 100, 500, 150)), ("1/20", (72, 650, 135, 690)),
             ("レンタルのみ", (490, 850, 680, 900))]
    result = screens.read_support_formation(np.zeros((1280, 720, 3), np.uint8), boxes)
    assert result["number"] == 7
    monkeypatch.setattr(ocr, "ocr", lambda *a, **k: [("7", .99)])
    assert screens.read_support_formation(np.zeros((1280, 720, 3), np.uint8), boxes)["number"] is None


def test_live_unknown_counter_stops_before_click(monkeypatch, capsys):
    from hiro import device
    from tools import support_inventory

    class FakeDevice:
        def screenshot(self):
            return None

        def click(self, *args):
            raise AssertionError("Unknown counter must not advance")

    row = {"number": None, "total": None, "slots": []}
    monkeypatch.setattr(device, "connect", FakeDevice)
    monkeypatch.setattr(screens, "read_support_formation", lambda _: row)
    assert support_inventory.live(20) == [row]
    assert "扫描不完整" in capsys.readouterr().out
