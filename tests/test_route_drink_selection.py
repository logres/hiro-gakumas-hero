import json
from types import SimpleNamespace as NS

import pytest

from hiro.brain.deciders import ProduceDeciders
from hiro.brain import route_drink_selection, route_policy
from hiro.brain.llm import LLMResult
from hiro.contracts import ActionKind, GameState


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_GENERIC_DRINK_SELECTION", "1")
    rows = {
        "idol": {"id": "idol", "name": "synthetic", "examEffectType": "ProduceExamEffectType_ExamReview", "planType": "ProducePlanType_Plan2"},
        "boost": {"name": "boost", "produceDescriptions": [{"text": "パラメータ上昇量増加30%（3ターン）体力消費2"}]},
        "copy": {"name": "copy", "produceDescriptions": [{"text": "効果をもう1回発動体力消費2消費体力増加1ターン"}]},
    }
    cat = NS(one=lambda table, key: rows[key])
    monkeypatch.setattr(route_policy, "catalog", lambda: cat)
    monkeypatch.setattr(route_drink_selection, "catalog", lambda: cat)

    class Model:
        name, model = "mock", "synthetic"
        response = {"action": "pick", "index": 1, "reason": "synthetic comparison"}
        calls = []

        def ask_json(self, system, user):
            self.calls.append((system, json.loads(user)))
            return LLMResult(self.response, json.dumps(self.response), .01, None, self.name, self.model)

    model = Model()
    current = GameState(produce={"idol_card_id": "idol", "mode": "produce-007", "step": 1}, page_fields={
        "candidates": [{"drink_id": "boost"}, {"drink_id": "copy"}, {"drink_id": None}], "held": [], "full": False})
    return ProduceDeciders(None, model, idol_card_id="idol"), model, current


def test_required_pick_uses_model_metadata_and_preserves_llm_trace(setup):
    decider, model, current = setup
    result = decider.decide("SELECT_DRINK", current, can_skip=False, n_options=3)
    assert result.action.args["pick_indexes"] == [1] and result.source == "llm"
    assert len(model.calls) == 1 and len(result.llm) == 1
    payload = model.calls[0][1]
    assert payload["held"] == [] and payload["full"] is False and payload["can_skip"] is False
    assert payload["idol"]["recommended_effect"].endswith("ExamReview")
    assert "体力消費2消費体力増加1ターン" in payload["candidates"][1]["effects"]
    assert "社区评级" not in str(payload) and "tiers" not in str(payload)


@pytest.mark.parametrize("response", [
    {"action": "pick", "index": -1, "reason": "invalid"},
    {"action": "pick", "index": 2, "reason": "unknown drink"},
    {"action": "pick", "index": True, "reason": "boolean"},
    {"action": "pick", "index": "1", "reason": "string"},
    {"action": "skip", "reason": "not allowed"},
    {"action": "discard", "index": 0, "reason": "not allowed"},
    {"action": "pick", "index": 1}, None,
])
def test_invalid_choice_never_falls_back_to_yaruki_and_keeps_trace(setup, response):
    decider, model, current = setup
    model.response = response
    result = decider.decide("SELECT_DRINK", current, can_skip=False, n_options=3)
    assert result.action.kind is ActionKind.WAIT and len(result.llm) == 1
    assert len(model.calls) == 1


def test_unknown_candidate_and_page_count_cannot_be_chosen(setup):
    decider, model, current = setup
    result = decider.decide("SELECT_DRINK", current, can_skip=False, n_options=1)
    assert result.action.kind is ActionKind.WAIT and len(result.llm) == 1
    assert [c["index"] for c in model.calls[0][1]["candidates"]] == [0]


def test_can_skip_allows_explicit_skip(setup):
    decider, model, current = setup
    model.response = {"action": "skip", "reason": "keep the empty capacity for later"}
    assert decider.decide("SELECT_DRINK", current, can_skip=True).action.kind is ActionKind.EXCLUDE_CARD


@pytest.mark.parametrize("full", [True, None])
def test_full_or_unknown_capacity_never_receives_or_discards_blindly(setup, full):
    decider, model, current = setup
    current.page_fields["full"] = full
    assert decider.decide("SELECT_DRINK", current, can_skip=False).action.kind is ActionKind.WAIT
    assert model.calls == []


def test_unknown_holding_stays_unknown_in_payload(setup):
    decider, model, current = setup
    del current.page_fields["held"]
    decider.decide("SELECT_DRINK", current, can_skip=False)
    assert model.calls[0][1]["held"] is None


def test_holding_fallback_accepts_dict_or_string_and_preserves_unknown_slots(setup):
    decider, model, current = setup
    del current.page_fields["held"]
    current.produce["drinks"] = [{"index": 2, "drink_id": "boost"}, None, "copy"]
    decider.decide("SELECT_DRINK", current, can_skip=False)
    held = model.calls[0][1]["held"]
    assert len(held) == 3 and held[0]["drink_id"] == "boost" and held[0]["index"] == 2
    assert held[1]["unknown"] is True and held[2]["drink_id"] == "copy"


def test_missing_model_and_default_off_keep_conservative_behavior(setup, monkeypatch):
    decider, model, current = setup
    monkeypatch.delenv("HIRO_GENERIC_DRINK_SELECTION", raising=False)
    assert decider.decide("SELECT_DRINK", current, can_skip=False).action.kind is ActionKind.WAIT
    assert model.calls == []
    monkeypatch.setenv("HIRO_GENERIC_DRINK_SELECTION", "1")
    decider.llm = None
    assert decider.decide("SELECT_DRINK", current, can_skip=False).action.kind is ActionKind.WAIT
