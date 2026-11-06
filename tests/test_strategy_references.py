import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from hiro.brain import strategy_references as refs
from hiro.brain.battle import BattleBrain, decision_record
from hiro.brain.cards import CardView
from hiro.brain.llm import LLMResult
from hiro.brain.state import BattleState


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_EXAM_STRATEGY_REFERENCES", "1")
    rows = {"review-a": {"examEffectType": "ProduceExamEffectType_ExamReview"},
            "review-b": {"examEffectType": "ProduceExamEffectType_ExamReview"},
            "yaruki": {"examEffectType": "ProduceExamEffectType_ExamCardPlayAggressive"}}
    return NS(one=lambda table, identity: rows[identity])


@pytest.mark.parametrize("identity,label,count", [
    ("review-a", "qualify-1", 1), ("review-b", "qualify-1", 1),
    ("review-a", "qualify-2", 0), ("review-a", "qualify-3", 0),
    ("review-a", "r1", 0), ("review-a", None, 0), ("review-a", "unknown", 0),
    ("yaruki", "qualify-1", 0), (None, "qualify-1", 0), ("missing", "qualify-1", 0),
])
def test_selection_requires_verified_mechanism_and_exact_first_exam(enabled, identity, label, count):
    selected = refs.select_references(identity, label, enabled)
    assert len(selected) == count
    if count:
        reference = selected[0]
        assert reference["status"] == "internal_candidate"
        assert reference["version"] and reference["source"] and reference["unknowns"]
        assert reference["applicability"]["exam_labels"] == ["qualify-1"]
        assert reference["sha256"] == hashlib.sha256((refs.REFERENCE_DIR / "review_engine_action.json").read_bytes()).hexdigest()


def test_switch_defaults_off_without_catalog_io(enabled, monkeypatch):
    monkeypatch.delenv("HIRO_EXAM_STRATEGY_REFERENCES", raising=False)
    monkeypatch.setattr(refs, "default_catalog", lambda: pytest.fail("Disabled references must not query master data"))
    assert refs.select_references("review-a", "qualify-1") == []


def battle():
    card = CardView(0, "synthetic", "synthetic-card", 2, True, "mental", 2, 0, None, "好印象+3")
    return BattleState("qualify-1", 1, 8, 30, 40, 5, [card], actions_left=1, impression=3, motivation=0)


def test_payload_and_llm_record_preserve_reference_version_full_hash_and_hand_identity(enabled):
    class Model:
        def ask_json(self, system, user):
            self.payload = json.loads(user.split("\n", 1)[1])
            return LLMResult({"action": "play:0", "reason": "synthetic advisory comparison"}, "", .01, adapter="mock")
    current = battle()
    current.strategy_references = refs.select_references("review-a", current.exam, enabled)
    model = Model()
    brain = BattleBrain(None, model)
    decision = brain._ask(current)
    reference = model.payload["strategy_references"][0]
    assert model.payload["hand"][0]["card_id"] == "synthetic-card"
    assert model.payload["hand"][0]["upgrade"] == 2
    assert brain.calls[-1]["prompt_version"] == brain.prompt_version + refs.audit_suffix(current.strategy_references)
    assert reference["version"] in brain.calls[-1]["prompt_version"]
    assert reference["sha256"][:12] in brain.calls[-1]["prompt_version"]
    assert decision_record(current, decision)["state"]["strategy_references"][0]["sha256"] == reference["sha256"]


def test_no_reference_keeps_original_prompt_version_and_hand_payload(enabled):
    current = battle()
    class Model:
        def ask_json(self, system, user):
            return LLMResult({"action": "play:0", "reason": "synthetic"}, "", 0, adapter="mock")
    brain = BattleBrain(None, Model())
    brain._ask(current)
    assert "strategy_references" not in current.to_prompt_dict()
    assert "card_id" not in current.to_prompt_dict()["hand"][0]
    assert brain.calls[-1]["prompt_version"] == brain.prompt_version


def test_screen_source_injects_only_into_generic_identity_context(enabled, monkeypatch):
    from hiro.defaults import exam_state
    from hiro.brain import exam_context
    monkeypatch.setattr(refs, "default_catalog", lambda: enabled)
    monkeypatch.setattr(exam_context, "verified_exam_context", lambda *a: {
        "identity": {"status": "verified_master", "recommended_effect": "ProduceExamEffectType_ExamReview"}})
    monkeypatch.setattr(exam_state, "screen_fields", lambda *a, **k: {"pitems": []})
    monkeypatch.setattr(exam_state, "screen_state", lambda *a, **k: battle())
    source = exam_state.ScreenExamStateSource()
    source.begin({"idol_card_id": "review-a", "exam": "qualify-1"})
    current, kind = source.read(NS(raw={"hand_layout": "normal"}, img=None), None)
    assert kind == "screen" and len(current.strategy_references) == 1
    assert current.recommended_effect == "ProduceExamEffectType_ExamReview"
    source.profile = object()
    current, _ = source.read(NS(raw={"hand_layout": "normal"}, img=None), None)
    assert current.strategy_references == []
    assert current.recommended_effect == "ProduceExamEffectType_ExamReview"
