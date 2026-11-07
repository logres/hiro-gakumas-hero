"""Synthetic current-frame status semantics through source, prompt and replay."""
import copy
import json
import os
from types import SimpleNamespace as NS

import pytest

from hiro.brain import status_evidence_context as evidence, plan_evidence
from hiro.brain.state import ExamMemory
from hiro.defaults import exam_state
from hiro.contracts import Action
from hiro.contracts.trace import freeze_exam_decision_input
from tools import replay_exam_choice as replay

pytestmark = pytest.mark.synthetic


def through_source(monkeypatch, rows):
    monkeypatch.setenv(evidence.FLAG, "1")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "0")
    source = exam_state.ScreenExamStateSource()
    source.begin({"exam": "qualify-3"})
    frame = NS(raw={"statuses": rows}, img=None, cards=[], drinks=[], remaining=3, hp=30, genki=0)
    state, _ = source.read(frame, ExamMemory("qualify-3"))
    context = json.loads(next(line[len(evidence.PREFIX):] for line in state.public_info.splitlines()
                              if line.startswith(evidence.PREFIX)))
    return state, context


def test_unknown_parameter_is_present_but_never_permanent(monkeypatch):
    state, context = through_source(monkeypatch, [{"slot": 0, "kind": "status", "key": "examlessonvaluemultiple",
                                                 "name": "parameter bonus", "value": None, "unit": None}])
    row = context["statuses"][0]
    assert row["value_status"] == row["duration_status"] == "unknown"
    assert state.buffs == {"parameter bonus": None}
    prompt = state.to_prompt_dict()
    assert prompt["buffs"] == {"parameter bonus": None}
    assert evidence.PREFIX in prompt["public_info"]
    assert "no_number_display" not in json.dumps(context)


def test_explicit_actual_permanence_survives_source_and_freeze(monkeypatch):
    raw = {"kind": "enchant", "name": "source", "card_id": "card", "value": None,
           "actual_duration_evidence": {"status": "permanent", "verified": True, "source": "current_screen"}}
    state, context = through_source(monkeypatch, [raw])
    assert context["statuses"][0]["duration_status"] == "permanent"
    assert context["statuses"][0]["value_status"] == "unknown"
    frozen = freeze_exam_decision_input(state, ExamMemory("qualify-3"), [Action.skip()], [],
        advisor=NS(profile=None), source=NS(confidence=lambda:"screen"), idol_card_id=None)
    serialized = json.loads(json.dumps(frozen, ensure_ascii=False))
    assert serialized["input"]["battle_state"]["public_info"] == state.public_info
    assert serialized["input"]["flags"][evidence.FLAG] is True
    raw["actual_duration_evidence"]["verified"] = False
    assert evidence.observed_status_context([raw])["statuses"][0]["duration_status"] == "unknown"


def test_catalog_candidate_is_not_actual_permanence(monkeypatch):
    state, context = through_source(monkeypatch, [{"kind": "enchant", "name": "source", "value": None,
        "permanent_proof": {"master_duration_basis": "candidate_only", "effect_turn": -1,
                            "effect_count": 0, "actual_duration_status": "unknown"}}])
    row = context["statuses"][0]
    assert row["catalog_duration_status"] == "permanent_candidate_only"
    assert row["duration_status"] == "unknown" and state.buffs["source"] is None
    assert "permanent_candidate_only" in state.to_prompt_dict()["public_info"]


@pytest.mark.parametrize("value,unit,expected", [(3,"ターン","finite"),(2,"回","finite"),
    (20,"%","unknown"),(3,None,"unknown"),(None,"ターン","unknown"),(True,"回","unknown")])
def test_finite_requires_read_number_and_explicit_counter_unit(value, unit, expected):
    row = evidence.observed_status_context([{"value": value, "unit": unit}])["statuses"][0]
    assert row["duration_status"] == expected


def test_plan_ignores_geometry_and_known_core_resource_changes_but_revalidates_trust():
    raw = {"slot": 0, "kind": "status", "key": "examcardplayaggressive", "value": 5}
    def state():
        return NS(hand=[], public_info=evidence.PREFIX+json.dumps(evidence.observed_status_context([raw])))
    baseline = plan_evidence.stamp([{"action":"play","card":"next"}], state())
    raw.update(slot=4, score=.9, rect=[1,2,3,4], screenshot_hash="changed", value=10)
    assert not plan_evidence.changed(baseline, state())
    raw["value"] = None
    assert plan_evidence.changed(baseline, state())
    unknown = plan_evidence.stamp(baseline, state())
    raw["value"] = 10
    assert plan_evidence.changed(unknown, state())
    raw.update(key="other", unit="回", value=2)
    finite = plan_evidence.stamp(baseline, state())
    raw["value"] = 1
    assert plan_evidence.changed(finite, state())
    assert plan_evidence.changed([{"action":"play","card":"next"}], state())


def test_default_off_and_legacy_replay_restores_ambient_flag(monkeypatch):
    monkeypatch.delenv(evidence.FLAG, raising=False)
    assert not evidence.enabled()
    source = exam_state.ScreenExamStateSource()
    source.begin({"exam":"qualify-3"})
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","0")
    frame = NS(raw={"statuses":[]}, img=None, cards=[], drinks=[], remaining=3, hp=30, genki=0)
    state, _ = source.read(frame, ExamMemory("qualify-3"))
    assert evidence.PREFIX not in (state.public_info or "")
    monkeypatch.setenv(evidence.FLAG,"1")
    saved = {key: False for key in replay.FLAGS if key != evidence.FLAG}
    before = copy.deepcopy(saved)
    with replay._flags(saved):
        assert os.environ[evidence.FLAG] == "0"
    assert saved == before and os.environ[evidence.FLAG] == "1"
    assert "src/hiro/brain/status_evidence_context.py" in replay.VERSION_FILES


@pytest.mark.parametrize("unit", ["ターン", "回"])
def test_positive_counter_conflicts_with_explicit_permanent(unit):
    raw = {"value": 3, "unit": unit,
           "actual_duration_evidence": {"status": "permanent", "verified": True, "source": "current_screen"}}
    row = evidence.observed_status_context([raw])["statuses"][0]
    assert row["value_status"] == "observed_number" and row["value"] == 3
    assert row["duration_status"] == "unknown"
    assert row["duration_conflict"] == "explicit_permanent_vs_observed_positive_counter"
    raw["unit"] = None
    row = evidence.observed_status_context([raw])["statuses"][0]
    assert row["duration_status"] == "permanent" and "duration_conflict" not in row


def test_core_projection_sorts_after_ignored_values_are_removed():
    rows = [{"kind":"status", "key":"examreview", "value":5, "name":"a"},
            {"kind":"status", "key":"examreview", "value":10, "name":"b"}]
    def state():
        return NS(hand=[], public_info=evidence.PREFIX+json.dumps(evidence.observed_status_context(rows)))
    old = plan_evidence.stamp([{"action":"play","card":"next"}], state())
    rows[0]["value"], rows[1]["value"] = 20, 1
    rows.reverse()
    assert not plan_evidence.changed(old, state())
