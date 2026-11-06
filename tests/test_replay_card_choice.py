"""Frozen SELECT_CARD comparison never borrows post-decision information."""

import json
import os

import pytest

from hiro.contracts import Action, Decision
from tools import replay_card_choice as replay


def _write_trace(tmp_path, *, page="SELECT_CARD", identity="i_card-skin-test", state_identity=None):
    trace = tmp_path / "trace"
    trace.mkdir()
    state = {"version": "1.2", "mode": "produce", "page": {"name": page},
             "produce": {"idol_card_id": state_identity, "mode": "produce-007", "step": 3, "deck": None},
             "page_fields": {"candidates": [{"card_id": "before", "upgrade": 0}]}}
    step = {"version": "1.2", "seq": 7, "observation": {"page": {"name": page}}, "state": state,
            "decision": {"action": {"kind": "ActivateEffect", "args": {"pick_indexes": [0]}}},
            "state_after": {"page_fields": {"candidates": [{"card_id": "future", "upgrade": 3}]}}}
    (trace / "steps.jsonl").write_text(json.dumps(step) + "\n", encoding="utf-8")
    (trace / "run.json").write_text(json.dumps({"idol": identity}), encoding="utf-8")
    return trace


def test_single_frame_uses_recorded_input_and_no_adapter_by_default(tmp_path, monkeypatch):
    trace = _write_trace(tmp_path)
    calls = []
    monkeypatch.setenv("HIRO_REVIEW_FIRST_EXAM_ROLES", "1")

    class FakeDecider:
        def __init__(self, profile, llm, *, idol_card_id):
            assert profile is None and llm is None and idol_card_id == "i_card-skin-test"

        def decide(self, page, state, *, n_options):
            assert page == "SELECT_CARD" and n_options == 1
            assert state.page_fields["candidates"][0]["card_id"] == "before"
            calls.append(os.environ["HIRO_MECHANISM_CARD_SELECTION"])
            if calls[-1] == "0":
                state.page_fields["candidates"][0]["card_id"] = "baseline-mutated"
            return Decision(Action.activate_effect(0), "frozen", "rule")

    monkeypatch.setattr(replay, "ProduceDeciders", FakeDecider)
    monkeypatch.setattr(replay, "from_spec", lambda spec: pytest.fail("default replay called an adapter"))
    monkeypatch.setattr(replay, "_versions", lambda: {"git_head": "test"})
    result = replay.compare(trace, 7)
    assert calls == ["0", "1"]
    assert result["identity"] == {"idol": "i_card-skin-test", "source": "run.json:idol"}
    assert result["state_summary"]["candidates"][0]["card_id"] == "before"
    assert result["policy_flags"]["baseline"]["HIRO_MECHANISM_CARD_SELECTION"] is False
    assert result["policy_flags"]["HIRO_REVIEW_FIRST_EXAM_ROLES"] is True
    assert result["recorded_action"]["kind"] == "ActivateEffect"
    assert result["adapter"] is None and "picked_musts" in " ".join(result["limits"])


def test_explicit_adapter_and_identity_are_bounded(tmp_path, monkeypatch):
    trace = _write_trace(tmp_path, state_identity="i_card-skin-test")
    adapters = []

    class FakeDecider:
        def __init__(self, profile, llm, *, idol_card_id):
            adapters.append(llm)

        def decide(self, page, state, *, n_options):
            return Decision(Action.activate_effect(0), "same action", "rule")

    monkeypatch.setattr(replay, "ProduceDeciders", FakeDecider)
    monkeypatch.setattr(replay, "from_spec", lambda spec: {"spec": spec})
    monkeypatch.setattr(replay, "_versions", lambda: {})
    result = replay.compare(trace, 7, idol="i_card-skin-test", adapter="codex:gpt-test")
    assert adapters == [None, {"spec": "codex:gpt-test"}]
    assert result["identity"]["source"] == "--idol"
    with pytest.raises(ValueError, match="仅接受"):
        replay.compare(trace, 7, adapter="claude:sonnet")
    with pytest.raises(ValueError, match="不同"):
        replay.compare(trace, 7, idol="i_card-other")


def test_rejects_non_card_and_missing_frames(tmp_path):
    trace = _write_trace(tmp_path, page="HIF_EXAM")
    with pytest.raises(ValueError, match="SELECT_CARD"):
        replay.compare(trace, 7)
    with pytest.raises(ValueError, match="恰好一帧"):
        replay.compare(trace, 8)


def test_rejects_card_frame_without_recorded_decision(tmp_path):
    trace = _write_trace(tmp_path)
    path = trace / "steps.jsonl"
    step = json.loads(path.read_text(encoding="utf-8"))
    step["decision"] = None
    path.write_text(json.dumps(step) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="原决策动作"):
        replay.compare(trace, 7)


def test_rejects_old_contract_even_with_decision(tmp_path):
    trace = _write_trace(tmp_path)
    path = trace / "steps.jsonl"
    step = json.loads(path.read_text(encoding="utf-8"))
    step["version"] = "1.0"
    path.write_text(json.dumps(step) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="早于 1.1"):
        replay.compare(trace, 7)
