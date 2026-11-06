"""Extra turns use their independent blue +N capsule, in full and fast HUD reads."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from hiro.brain.state import ExamMemory
from hiro.vision import hif


def capsule(text="12"):
    img = np.zeros((1280, 720, 3), np.uint8)
    cv2.rectangle(img, (98, 122), (177, 155), (255, 255, 255), -1)
    blue = (255, 180, 0)
    cv2.line(img, (110, 138), (123, 138), blue, 3)
    cv2.line(img, (116, 132), (116, 145), blue, 3)
    x = 130
    for char in text:
        template = hif._templates()[char]
        glyph = cv2.resize(template.astype(np.uint8), (round(template.shape[1]*19/40), 19),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
        img[129:148, x:x+glyph.shape[1]][glyph] = blue
        x += glyph.shape[1] + 4
    return img


def test_absent_unknown_and_multidigit_bonus(monkeypatch):
    assert hif.read_extra_turns(np.zeros((1280, 720, 3), np.uint8)) == 0
    assert hif.read_extra_turns(capsule("")) is None
    assert hif.read_extra_turns(capsule()) == 12
    monkeypatch.setattr(hif, "_templates", lambda: {})
    assert hif.read_extra_turns(capsule("")) is None


def test_fast_and_full_share_total_and_preserve_unknown(monkeypatch):
    monkeypatch.setattr(hif, "read_int", lambda *a, **kw: 1)
    monkeypatch.setattr(hif, "read_number", lambda *a, **kw: 1)
    img = capsule()
    assert hif.read_remaining_turns(img) == 13
    assert hif.read_hif_hud(img)["remaining_turns"] == 13
    assert hif.read_hif_hud(img, fallback=True)["remaining_turns"] == 13
    assert hif.read_remaining_turns(capsule("")) is None


def test_recorded_extra_final_turn_resets_memory():
    frames = Path(__file__).resolve().parents[1] / "traces/windows-qualify-04-r15/frames"
    if not all((frames / f"{n:05}.jpg").exists() for n in (55, 56, 58)):
        pytest.skip("local trace screenshots not distributed")
    values = [hif.read_hif_hud(cv2.imread(str(frames / f"{n:05}.jpg")))["remaining_turns"]
              for n in (55, 56, 58)]
    assert values == [2, 2, 1]
    memory = ExamMemory("qualify-3")
    assert memory.observe_turn(values[0])
    assert not memory.observe_turn(values[1])
    memory.actions_left = 0
    assert memory.observe_turn(values[2])
    assert memory.actions_left == 1


def test_adding_turn_does_not_start_new_turn():
    memory = ExamMemory("qualify-3")
    memory.observe_turn(4)
    assert not memory.observe_turn(5)
    assert memory.turn == 1
    assert memory.observe_turn(4)
    assert memory.turn == 2


def test_executor_frame_uses_total_and_never_falls_back_to_main(monkeypatch):
    from hiro.exec import exam

    monkeypatch.setattr(hif, "read_number", lambda *a, **kw: 1)
    monkeypatch.setattr(exam, "_read_int", lambda *a, **kw: 999)
    monkeypatch.setattr(exam, "locate_cards", lambda img: [])
    monkeypatch.setattr(exam, "_drinks", lambda img: [])
    assert exam.Frame(capsule()).remaining == 13
    assert exam.Frame(capsule("")).remaining is None
    assert exam._hud_int(capsule(""), hif.BOX_TURNS, None) is None

def test_tiny_blue_edge_scenery_does_not_poison_visible_digit():
    img = capsule("1")
    # White background joins the pill, with disconnected blue scenery at its edge.
    img[120:156, 95:178] = (255, 255, 255)
    original = capsule("1")
    blue = (255, 180, 0)
    mask = np.any(original != 0, axis=2) & np.any(original != 255, axis=2)
    img[mask] = original[mask]
    img[125:133, 176:178] = blue
    assert hif.read_extra_turns(img) == 1


def test_interior_unknown_glyph_stays_unknown():
    img = capsule("1")
    img[130:138, 164:166] = (255, 180, 0)
    assert hif.read_extra_turns(img) is None


def test_recorded_scenery_beside_extra_turn_capsule():
    paths = [Path("traces/windows-qualify-04-r20/frames/00005.jpg"),
             Path("reports/runs/20261107-061134/frames/00030-battle_decision.jpg")]
    paths = [Path(__file__).resolve().parents[1] / path for path in paths]
    if not all(path.exists() for path in paths):
        pytest.skip("local trace screenshots not distributed")
    for path in paths:
        img = cv2.imread(str(path))
        assert hif.read_extra_turns(img) == 1
        assert hif.read_remaining_turns(img) == 3

