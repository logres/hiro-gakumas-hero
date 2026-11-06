"""Replay the numeric tokens observed at native/enlarged RapidOCR scales."""

import numpy as np
import pytest


@pytest.mark.parametrize("enabled,points,growth,vo_text", [
    (False, 26, {"vo": 3.0, "da": 566.2, "vi": 558.0}, "34.3%"),
    (True, 260, {"vo": 34.3, "da": 56.2, "vi": 55.8}, "34.3%"),
    (True, 260, {"vo": None, "da": 56.2, "vi": 55.8}, "7 34.3%"),
    (True, 260, {"vo": None, "da": 56.2, "vi": 55.8}, "34.3%7"),
])
def test_action_hud_uses_opt_in_native_numeric_crops(monkeypatch, enabled, points, growth, vo_text):
    from hiro.vision import action

    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", raising=False)
    if enabled:
        monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    # Mark each real HUD crop so this tests the reader's field wiring and parser,
    # including fragmented P digits, without invoking any OCR model or device.
    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    native = {1: ["2", "60"], 2: [vo_text], 3: ["56.2%"], 4: ["55.8%"]}
    enlarged = {1: ["2", "6"], 2: [".3%", "-"], 3: ["56", "6", ".2%"], 4: ["5", "5", "8%"]}
    for mark, box in enumerate([action.POINTS_BOX, *action.GROWTH_BOXES.values()], 1):
        x1, y1, x2, y2 = box
        image[y1:y2, x1:x2] = mark

    calls = []

    def ocr(crop, *, scale, languages=None):
        mark = int(crop[0, 0, 0])
        if mark in native:
            calls.append((mark, scale))
            if enabled and mark > 1:
                # A chevron on the old crop's left edge must be excluded before
                # OCR, rather than guessing that a leading numeric digit is bad.
                expected_box = list(action.WINDOWS_GROWTH_TEXT_BOXES.values())[mark - 2]
                assert crop.shape[1] == expected_box[2] - expected_box[0]
            tokens = (native if scale == 1 else enlarged)[mark]
        else:
            tokens = []
        return [(token, 0.99) for token in tokens]

    monkeypatch.setattr(action, "ocr", ocr)
    monkeypatch.setattr(action, "read_stamina", lambda _: (45, 45))
    monkeypatch.setattr(action, "read_number", lambda img, box: 260 if box == action.POINTS_BOX else 0)
    monkeypatch.setattr(action, "_options", lambda _: [])
    result = action.read_action_select(image)
    assert result.p_points == points
    assert result.growth_pct == growth
    assert calls == [(i, 1 if enabled else 4) for i in range(2 if enabled else 1, 5)]


@pytest.mark.parametrize("values,exam,expected", [
    ([3, 3], "選抜試験1", 3), ([6, 6], "H.I.F本戦", 6),
    ([0, 0], "選抜試験3", 0), ([3, 4], "選抜試験1", None),
    ([None, None], "選抜試験1", None), ([7, 7], "選抜試験1", None),
    ([3, 3], None, None), ([3, 3], "不明", None),
])
def test_day_digit_fallback_needs_exam_and_two_in_range_votes(monkeypatch, values, exam, expected):
    from hiro.vision import action
    votes = iter(values)
    boxes = []
    monkeypatch.setattr(action, "read_dddd", lambda img, box: boxes.append(box) or next(votes))
    assert action._read_windows_days(None, exam) == expected
    assert len(boxes) == (2 if exam and ("試験" in exam or "本戦" in exam) else 0)


@pytest.mark.parametrize("fields", [
    {}, {"mode": "produce-007"}, {"step": 4},
    {"mode": "produce-007", "step": 4, "produce_point": 370, "params": {"Vo": 328, "Da": 283, "Vi": 449}, "options": []},
    {"mode": "produce-007", "step": 4, "produce_point": 370, "stamina": 34,
     "params": {"Vo": 328, "Da": 283, "Vi": 449}, "options": [], "complete": False},
])
def test_missing_fresh_day_stops_before_review_or_decision(monkeypatch, fields):
    from types import SimpleNamespace as NS
    from hiro.produce.hif import HiroHifStrategy, ACTION_REQUIRED
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    seen = []
    strategy = HiroHifStrategy.__new__(HiroHifStrategy)
    strategy.s = NS(observe_complete=lambda page, required: seen.append(required) or NS(fields=fields),
                    state=NS(produce={"mode": "produce-007", "step": 3, "stamina": 39}))
    strategy._maybe_review_deck = lambda: pytest.fail("Missing fresh day must stop before UI or decisions")

    class Stopped(Exception):
        pass

    def stop(*args, **kwargs):
        raise Stopped

    strategy._stop = stop
    with pytest.raises(Stopped):
        strategy.on_action_select(None)
    assert seen == [(*ACTION_REQUIRED, "mode", "step")]


@pytest.mark.parametrize("enabled,expected_kind,expected_attr", [(False, "lesson", None), (True, "open_lesson", "vo")])
def test_windows_vocal_lesson_zero_is_normalized_only_in_known_label(monkeypatch, enabled, expected_kind, expected_attr):
    from hiro.vision import action
    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", raising=False)
    if enabled:
        monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    monkeypatch.setattr(action, "ocr_boxes", lambda *a, **k: [("V0公開レッスン", .99, (130, 210, 250, 240))])
    result = action._options(np.zeros((1280, 720, 3), dtype=np.uint8))
    assert len(result) == 1 and (result[0].kind, result[0].attr) == (expected_kind, expected_attr)


@pytest.mark.parametrize("tokens,expected", [
    (["34/", "/45"], (34, 45)), (["45/45"], (45, 45)), (["0/45"], (0, 45)),
    (["34/45", "/45"], None), (["34/", "/0"], None), (["46/45"], None),
    (["3445"], None), (["HP34/45"], None),
])
def test_windows_stamina_allows_only_complete_fraction_with_slash_overlap(monkeypatch, tokens, expected):
    from hiro.vision import action
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    calls = []
    monkeypatch.setattr(action, "ocr", lambda *a, **k: calls.append(k["scale"]) or [(t, .99) for t in tokens])
    assert action.read_stamina(np.zeros((1280, 720, 3), dtype=np.uint8)) == expected
    assert calls == [1]
