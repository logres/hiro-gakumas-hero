import numpy as np
import pytest

from hiro.vision import action


def test_real_ocr_deformations_recover_from_independent_prefix_not_columns(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    # Actual deformations Y0 / Dä / V山 and missing ン; deliberately move their
    # positions so a fixed Vo-left / Da-middle / Vi-right guess would fail.
    tokens = [("V山公開レッス", .79, (92, 243, 252, 264)),
              ("Y0公開レッスン", .89, (466, 243, 622, 264)),
              ("Dä公開レッスン", .94, (278, 243, 440, 264))]
    monkeypatch.setattr(action, "ocr_boxes", lambda *a, **k: tokens)
    votes = iter(["Vi.", "Vi.", "Vo.", "Vo.", "Da.", "Da."])
    scales = []

    def ocr(crop, *, scale, languages):
        scales.append(scale)
        assert languages == ("en-US",) and (crop[:8] == 255).all()
        return [(next(votes), .99)]

    monkeypatch.setattr(action, "ocr", ocr)
    options = action._options(np.zeros((1280, 720, 3), dtype=np.uint8))
    assert [(o.label, o.attr) for o in options] == [
        ("V山公開レッス", "vi"), ("Dä公開レッスン", "da"), ("Y0公開レッスン", "vo")]
    assert all(o.kind == "open_lesson" for o in options)
    assert scales == [2, 4, 2, 4, 2, 4]


@pytest.mark.parametrize("votes", [[("Da.", .99), ("Vi.", .99)], [("Vi.", .89)],
                                    [("V山", .99)], [("Vi.1", .99)], []])
def test_ambiguous_prefix_keeps_unknown_lesson_and_incomplete_guard(monkeypatch, votes):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    monkeypatch.setattr(action, "ocr_boxes", lambda *a, **k: [("V山公開レッス", .79, (466, 243, 622, 264))])
    values = iter(votes)
    monkeypatch.setattr(action, "ocr", lambda *a, **k: [next(values)] if votes else [])
    options = action._options(np.zeros((1280, 720, 3), dtype=np.uint8))
    assert len(options) == 1 and options[0].attr is None
    state = action.ActionSelectState("選抜試験3", 5, 36, 45, 620,
                                    {"vo": 617, "da": 778, "vi": 1308}, {}, {}, 483, None, options)
    assert state.complete is False


def test_recovery_default_off_does_not_call_english_reader(monkeypatch):
    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", raising=False)
    monkeypatch.setattr(action, "ocr_boxes", lambda *a, **k: [("Dä公開レッスン", .94, (278, 243, 440, 264))])
    monkeypatch.setattr(action, "ocr", lambda *a, **k: pytest.fail("Default off must preserve existing OCR path"))
    assert action._options(np.zeros((1280, 720, 3), dtype=np.uint8))[0].attr is None
