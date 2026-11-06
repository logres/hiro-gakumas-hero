"""Exam label is observable; frame comparison notes stay outside replay state."""

from types import SimpleNamespace

import numpy as np

from hiro.brain.state import CAMPUS_HIRO, ExamMemory
from hiro.contracts import TraceWriter
from hiro.defaults.exam_state import ScreenExamStateSource, screen_fields, screen_state
from hiro.loop.replay import report
from hiro.loop.session import Session


def test_exam_label_observation_replays(tmp_path):
    session = Session(TraceWriter(root=tmp_path, name="exam"))
    screen_fields({"exam_label": "qualify-1", "remaining_turns": 7}, session,
                  img=np.zeros((1280, 720, 3), dtype=np.uint8))
    assert session.last.fields["exam_label"] == "qualify-1"
    assert session.state.exam_session.label == "qualify-1"
    session.record(session.last)
    session.trace.close()
    assert report(session.trace.dir / "steps.jsonl")["state_mismatch_vs_trace"] == []


def test_hand_disagreement_is_preserved_as_step_note_not_state_conflict(tmp_path):
    session = Session(TraceWriter(root=tmp_path, name="exam"))
    screen_fields({"exam_label": "qualify-1", "remaining_turns": 7}, session,
                  img=np.zeros((1280, 720, 3), dtype=np.uint8))
    frame = SimpleNamespace(cards=[], drinks=[], remaining=7, hp=18, genki=5, hand=None)
    # OCR supplied a card, but the click locator found no corresponding slot.
    recognized = {"slot": 0, "name": "ファンサの基本", "card_id": "card-a",
                  "available": True, "upgrade": 0, "category": "active", "cost": 0,
                  "hp_cost": 0, "extra_cost": None, "text": ""}
    screen_state(ExamMemory(exam="qualify-1"), CAMPUS_HIRO,
                 {"remaining_turns": 7, "hand": [recognized]}, frame,
                 conflicts=session.notes)
    assert any("考试手牌" in note for note in session.notes)
    assert session.state.conflicts == []
    step = session.record(session.last)
    session.trace.close()
    assert any("考试手牌" in note for note in step.notes)
    assert report(session.trace.dir / "steps.jsonl")["state_mismatch_vs_trace"] == []


def test_source_sends_exam_label_and_diagnostics_to_session(monkeypatch, tmp_path):
    import hiro.defaults.exam_state as exam_state

    session = Session(TraceWriter(root=tmp_path, name="exam"))
    seen = []
    recognized = {"slot": 0, "name": "ファンサの基本", "card_id": "card-a",
                  "available": True, "upgrade": 0, "category": "active", "cost": 0,
                  "hp_cost": 0, "extra_cost": None, "text": ""}

    def fields(raw, current_session=None, img=None):
        seen.append(raw.get("exam_label"))
        return {"remaining_turns": 7, "hand": [recognized]}

    monkeypatch.setattr(exam_state, "screen_fields", fields)
    source = ScreenExamStateSource()
    source.begin({"exam": "qualify-1", "profile": CAMPUS_HIRO, "session": session})
    frame = SimpleNamespace(raw={"hand_layout": "ok"}, cards=[], drinks=[], remaining=7,
                            hp=18, genki=5, hand=None, img=None)
    state, why = source.read(frame, ExamMemory(exam="qualify-1"))
    assert state is not None and why == "screen" and seen == ["qualify-1"]
    assert any("考试手牌" in note for note in session.notes)
    assert session.state.conflicts == []
    session.trace.close()
