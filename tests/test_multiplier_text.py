"""Japanese OCR punctuation must not drop a valid multiplier vote."""
import pytest

from hiro.vision import hif


@pytest.mark.parametrize("text,expected", [
    ("ビジュアル2868％", 2868),
    ("ビジュアル2868％1", 2868),
    ("ビジュアル2868%", 2868),
    ("ビジュアル2868", None),
])
def test_multiplier_requires_percent_but_accepts_japanese_width(text, expected):
    assert hif._parse_attr(text) == {"attr": "visual", "multiplier_pct": expected}


def test_fullwidth_percent_still_requires_independent_digit_agreement(monkeypatch):
    import numpy as np
    monkeypatch.setattr(hif, "_MULT_SEEN", {})
    value = hif._parse_attr("ビジュアル2868％")["multiplier_pct"]
    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    monkeypatch.setattr(hif, "read_dddd", lambda *a: 868)
    assert hif._vote_multiplier(image, value, None, "visual")[0] is None
    monkeypatch.setattr(hif, "read_dddd", lambda *a: 2868)
    assert hif._vote_multiplier(image, value, None, "visual")[0] == 2868
