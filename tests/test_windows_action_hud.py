"""Replay the numeric tokens observed at native/enlarged RapidOCR scales."""

import numpy as np
import pytest


@pytest.mark.parametrize("enabled,points,growth", [
    (False, 26, {"vo": 3.0, "da": 566.2, "vi": 558.0}),
    (True, 260, {"vo": 34.3, "da": 56.2, "vi": 55.8}),
])
def test_action_hud_uses_opt_in_native_numeric_crops(monkeypatch, enabled, points, growth):
    from hiro.vision import action

    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", raising=False)
    if enabled:
        monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    # Mark each real HUD crop so this tests the reader's field wiring and parser,
    # including fragmented P digits, without invoking any OCR model or device.
    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    native = {1: ["2", "60"], 2: ["34.3%"], 3: ["56.2%"], 4: ["55.8%"]}
    enlarged = {1: ["2", "6"], 2: [".3%", "-"], 3: ["56", "6", ".2%"], 4: ["5", "5", "8%"]}
    for mark, box in enumerate([action.POINTS_BOX, *action.GROWTH_BOXES.values()], 1):
        x1, y1, x2, y2 = box
        image[y1:y2, x1:x2] = mark

    calls = []

    def ocr(crop, *, scale, languages=None):
        mark = int(crop[0, 0, 0])
        if mark in native:
            calls.append((mark, scale))
            tokens = (native if scale == 1 else enlarged)[mark]
        else:
            tokens = []
        return [(token, 0.99) for token in tokens]

    monkeypatch.setattr(action, "ocr", ocr)
    monkeypatch.setattr(action, "read_stamina", lambda _: (45, 45))
    monkeypatch.setattr(action, "read_number", lambda *a: 0)
    monkeypatch.setattr(action, "_options", lambda _: [])
    result = action.read_action_select(image)
    assert result.p_points == points
    assert result.growth_pct == growth
    assert calls == [(i, 1 if enabled else 4) for i in range(1, 5)]
