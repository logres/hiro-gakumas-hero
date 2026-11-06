"""Status-column holes must not erase later, currently observed effects."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from hiro.vision import status
from hiro.vision.observe import battle_observation


def read_synthetic(monkeypatch, scores, entries):
    inspected, read = [], []

    def score(img, slot):
        inspected.append(slot)
        return scores.get(slot, 0)

    def read_slot(img, slot):
        read.append(slot)
        return {"slot": slot, **entries[slot]}

    monkeypatch.setattr(status, "diamond_score", score)
    monkeypatch.setattr(status, "_read_slot", read_slot)
    rows = status.read_status_column(np.zeros((1280, 720, 3), dtype=np.uint8))
    assert inspected == list(range(status.MAX_SLOTS))
    return rows, read


def observed(rows):
    return battle_observation({"statuses": rows, "status": status.status_summary(rows)})


def test_middle_low_outline_keeps_unknown_and_reads_later_current_value(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {0: 1, 1: .333, 2: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
        2: {"kind": "status", "key": "examcardplayaggressive", "value": 25},
    })
    assert read == [0, 2]
    assert rows[1]["uncertain"] == "slot_outline"
    assert [r["slot"] for r in rows] == [0, 1, 2]
    assert observed(rows)["motivation"] == 25


def test_middle_unknown_prevents_absence_becoming_zero(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1, 2: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
        2: {"kind": "enchant", "name": "known enchant", "value": None},
    })
    assert observed(rows)["motivation"] is None
    assert observed(rows)["impression"] == 161


def test_trailing_empty_slots_are_not_unknown_middle_slots(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {0: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
    })
    assert read == [0] and len(rows) == 1
    assert observed(rows)["motivation"] is None


def test_low_scoring_final_icon_cannot_turn_missing_status_into_zero(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {0: 1, 1: .333}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
    })
    assert read == [0]
    assert observed(rows)["motivation"] is None


def test_explicit_inactive_icon_still_confirms_zero(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1}, {
        0: {"kind": "status", "key": "examcardplayaggressive", "value": 0, "inactive": True},
    })
    assert observed(rows)["motivation"] == 0


def test_recognized_icon_with_unreadable_number_is_unknown(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1}, {
        0: {"kind": "status", "key": "examcardplayaggressive", "value": None},
    })
    assert observed(rows)["motivation"] is None


def test_unknown_blue_icon_keeps_absent_state_unknown(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1, 1: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
        1: {"kind": "status", "key": None, "value": 25},
    })
    assert observed(rows)["motivation"] is None


def test_empty_column_is_unknown(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {}, {})
    assert rows == read == []
    assert observed(rows)["motivation"] is None


def test_unidentified_nonblue_slot_cannot_prove_status_absence():
    rows = [{"slot": 0, "kind": "status", "key": "examreview", "value": 161},
            {"slot": 1, "kind": "enchant", "card_id": None, "value": None}]
    assert observed(rows)["motivation"] is None


def test_sparse_external_column_does_not_claim_absence():
    rows = [{"slot": 0, "kind": "status", "key": "examreview", "value": 161},
            {"slot": 2, "kind": "enchant", "value": None}]
    assert observed(rows)["motivation"] is None


def test_initial_unknown_core_values_reach_model_without_stopping(monkeypatch):
    from hiro.brain.cards import CardView, parse_tags
    from hiro.brain.llm import MockLLM
    from hiro.brain.state import BattleState, ExamMemory, UNKNOWN
    from hiro.contracts import Action
    from hiro.defaults.advisor import RuleLLMAdvisor

    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    values = observed([])
    hand = CardView(0, "setup", "synthetic", 0, True, "mental", 0, 0, None,
                    "好印象+3", parse_tags("setup", "好印象+3"))
    current = BattleState("qualify-1", 1, 10, 30, 45, 0, [hand],
                          motivation=values["motivation"], impression=values["impression"])
    payload = current.to_prompt_dict()
    assert all(name in payload["unknown"] for name in ("motivation", "impression"))
    assert payload["motivation"] == payload["impression"] == UNKNOWN
    llm = MockLLM([{"action": "play:0", "reason": "visible setup"}])
    advisor = RuleLLMAdvisor(None, llm)
    result = advisor.decide(current, ExamMemory("qualify-1"), None,
                            [Action.from_legal(a) for a in current.legal_actions()])
    assert result.action.legal_key() == "play:0" and len(llm.calls) == 1


def test_local_r15_seq53_reads_visible_motivation_25(monkeypatch):
    # Local evidence stays in ignored traces; no screenshot is added to git.
    path = Path(__file__).resolve().parents[1] / "traces/windows-qualify-04-r15/frames/00053.jpg"
    if not path.exists():
        pytest.skip("local r15 evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND", "hiro.platforms.windows.ocr")
    image = cv2.imread(str(path))
    rows = status.read_status_column(image)
    assert len(rows) == 8
    assert rows[1]["uncertain"] == "slot_outline"
    assert observed(rows)["motivation"] == 25
    assert observed(rows)["impression"] == 161
