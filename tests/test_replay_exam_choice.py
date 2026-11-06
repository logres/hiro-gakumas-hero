"""A frozen exam decision must be complete and isolated from other comparisons."""

import hashlib
import json
import os
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from hiro.brain.cards import CardView
from hiro.brain.llm import LLMResult
from hiro.brain.state import BattleState, ExamMemory
from hiro.contracts import Action
from hiro.contracts.trace import freeze_exam_decision_input
from tools import replay_exam_choice as replay


def _trace(tmp_path):
    state = BattleState(exam="qualify-1", turn=1, remaining_turns=10, hp=30, max_hp=40, genki=0,
                        hand=[CardView(0, "test", "card-test", 0, True, "mental", 0, 0, None, "元気+1")])
    memory = ExamMemory(exam="qualify-1", turn=1, last_remaining=10)
    payload = {"battle_state": asdict(state), "exam_memory": memory.to_dict(),
               "legal": [Action.from_legal(a).to_dict() for a in state.legal_actions()], "previews": [],
               "profile": None, "advisor": "hiro.defaults.advisor.RuleLLMAdvisor",
               "source": "hiro.defaults.exam_state.ScreenExamStateSource", "source_confidence": "screen",
               "idol_card_id": "test-idol", "flags": {name: False for name in replay.FLAGS}}
    frozen = {"schema_version": "1.0", "sha256": hashlib.sha256(replay._canonical(payload)).hexdigest(), "input": payload}
    step = {"seq": 7, "observation": {"page": {"name": "HIF_EXAM"}},
            "decision": {"action": Action.play_card(0).to_dict(), "reason": "recorded", "llm": []},
            "exam_decision_input": frozen}
    path = tmp_path / "steps.jsonl"
    path.write_text(json.dumps(step, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_complete_frozen_rule_replay_without_model(tmp_path, monkeypatch):
    path = _trace(tmp_path)
    monkeypatch.setenv("HIRO_LLM", "codex")  # default replay must still be offline
    result = replay.compare(path, 7)
    assert result["input_sha256"]
    assert result["rule_baseline_legal"] is True
    assert result["model_decision"] is None
    assert result["model_calls_used"] == 0
    assert result["recorded_legal"] is True


def test_old_or_incomplete_input_is_rejected(tmp_path):
    path = _trace(tmp_path)
    step = json.loads(path.read_text(encoding="utf-8"))
    del step["exam_decision_input"]
    path.write_text(json.dumps(step) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="旧 trace"):
        replay.compare(path, 7)
    path = _trace(tmp_path)
    step = json.loads(path.read_text(encoding="utf-8"))
    del step["exam_decision_input"]["input"]["exam_memory"]["plan"]
    step["exam_decision_input"]["sha256"] = hashlib.sha256(
        replay._canonical(step["exam_decision_input"]["input"])).hexdigest()
    path.write_text(json.dumps(step) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ExamMemory 字段不完整"):
        replay.compare(path, 7)


def test_model_comparison_gets_fresh_input(tmp_path, monkeypatch):
    path = _trace(tmp_path)
    seen = []

    def fake_decide(payload, adapter=None):
        seen.append(payload["exam_memory"]["turn"])
        payload["exam_memory"]["turn"] = 999
        return {"action": Action.skip().to_dict(), "warnings": [], "llm": []}

    class FakeAdapter:
        name, model = "fake", "fake"

        def ask_json(self, system, user):
            raise AssertionError("fake_decide should not call model")

    monkeypatch.setattr(replay, "_decide", fake_decide)
    monkeypatch.setattr(replay, "from_spec", lambda spec: FakeAdapter())
    result = replay.compare(path, 7, adapter="codex")
    assert seen == [1, 1]
    assert result["model_legal"] is True


def test_capture_copies_state_and_memory_before_advisor_mutates(monkeypatch):
    state = BattleState(exam="qualify-1", turn=1, remaining_turns=10, hp=30, max_hp=40, genki=0,
                        hand=[CardView(0, "before", "card-test", 0, True, "mental", 0, 0, None, "元気+1")])
    memory = ExamMemory(exam="qualify-1", turn=1, plan=[{"action": "play", "card": "before"}])
    monkeypatch.setenv("HIRO_FALLBACK_DRINKS", "1")
    advisor = SimpleNamespace(profile=None)
    source = SimpleNamespace(confidence=lambda: "screen")
    frozen = freeze_exam_decision_input(state, memory, [Action.play_card(0)], [], advisor=advisor,
                                        source=source, idol_card_id="test-idol")
    state.hand[0].name = "after"
    memory.plan[0]["card"] = "after"
    assert frozen["input"]["battle_state"]["hand"][0]["name"] == "before"
    assert frozen["input"]["exam_memory"]["plan"][0]["card"] == "before"
    assert frozen["input"]["flags"]["HIRO_FALLBACK_DRINKS"] is True
    assert frozen["sha256"] == hashlib.sha256(replay._canonical(frozen["input"])).hexdigest()


def test_replay_uses_frozen_drink_flag_over_external_environment(tmp_path, monkeypatch):
    path = _trace(tmp_path)
    step = json.loads(path.read_text(encoding="utf-8"))
    payload = step["exam_decision_input"]["input"]
    payload["flags"]["HIRO_FALLBACK_DRINKS"] = True
    payload["battle_state"]["remaining_turns"] = 1
    payload["battle_state"]["actions_left"] = 1
    step["exam_decision_input"]["sha256"] = hashlib.sha256(replay._canonical(payload)).hexdigest()
    path.write_text(json.dumps(step, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setenv("HIRO_FALLBACK_DRINKS", "0")
    from hiro.brain.fallback_drinks import _ready

    def check_flag(payload, adapter=None):
        state, *_ = replay._state(payload)
        assert _ready(state) is True
        return {"action": Action.skip().to_dict(), "warnings": [], "llm": []}

    monkeypatch.setattr(replay, "_decide", check_flag)
    assert replay.compare(path, 7)["flags"]["HIRO_FALLBACK_DRINKS"] is True
    assert os.environ["HIRO_FALLBACK_DRINKS"] == "0"


def test_model_call_limit_is_enforced_in_full_decision_chain(tmp_path, monkeypatch):
    path = _trace(tmp_path)
    calls = []

    class InvalidAdapter:
        name, model = "fake", "fake"

        def ask_json(self, system, user):
            calls.append(user)
            return LLMResult({"action": "play:99", "reason": "invalid"}, '{"action":"play:99"}',
                             0.0, adapter=self.name, model=self.model)

    monkeypatch.setattr(replay, "from_spec", lambda spec: InvalidAdapter())
    result = replay.compare(path, 7, adapter="codex", max_model_calls=1)
    assert len(calls) == result["model_calls_used"] == 1
    assert result["model_decision"]["source"] == "fallback"
    assert any("limit reached" in (row.get("error") or "") for row in result["model_decision"]["llm"])
