"""Public schedule can disagree with observed options; unavailable gains stay unknown."""

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from hiro.state import context
from hiro.state.produce import LessonOption, ProduceState, SELECTION


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_PUBLIC_LESSON_FALLBACK", "1")
    public = json.loads((Path(__file__).parents[1] / "src/hiro/defaults/schedule_hif.json").read_text(encoding="utf-8"))
    stages = public[SELECTION]
    monkeypatch.setattr(context, "schedule", lambda _: context.Schedule(stages))
    state = ProduceState("idol", SELECTION, 3, 39, 45, 370,
                         {a: 200 for a in context.ATTRS}, {a: 1000 for a in context.ATTRS}, 60)
    return state, stages


def test_observed_training_on_public_nontraining_stage_stays_unknown(setup, monkeypatch):
    state, _ = setup
    monkeypatch.setattr(context, "catalog", lambda: pytest.fail("No lesson IDs: must not guess a catalog row"))
    monkeypatch.setattr(context, "r1_bonus_gain", lambda *a: pytest.fail("Unknown gains must not produce a numeric preview"))
    rows = context.preview_action_select(state, [{"option": "training", "attr": "Vi", "hp_cost": 8}])
    assert len(rows) == 1
    assert (rows[0]["option"], rows[0]["attr"], rows[0]["sp"]) == ("training", "Vi", True)
    assert rows[0]["delta"] == {} and "未知" in rows[0]["预演"]


def test_public_fallback_is_disabled_by_default(setup, monkeypatch):
    state, _ = setup
    monkeypatch.delenv("HIRO_PUBLIC_LESSON_FALLBACK", raising=False)
    with pytest.raises(KeyError, match="open_lesson_ids"):
        context.preview_lessons(state, [LessonOption("Vi", "Da", True)])


@pytest.mark.parametrize("missing", ["base_p_points", "catalog_row", "exact_variant", "gain_column"])
def test_missing_public_lesson_data_has_no_fabricated_gain(setup, monkeypatch, missing):
    state, stages = setup
    state.step = 2
    if missing == "base_p_points":
        stages[1].pop("base_p_points")

    def one(table, key):
        assert table == "ProduceStepOpenLesson"
        if missing == "catalog_row":
            raise KeyError(key)
        row = {"id": key, "subParameterType": "ParameterType_Visual" if missing == "exact_variant" else "ParameterType_Dance",
               "mainParameter": 50, "subParameter": 20, "star": 10, "stamina": 8}
        if missing == "gain_column":
            row.pop("mainParameter")
        return row

    monkeypatch.setattr(context, "catalog", lambda: NS(one=one))
    rows = context.preview_lessons(state, [LessonOption("Vi", "Da", True)])
    assert len(rows) == 1 and rows[0]["delta"] == {} and "未知" in rows[0]["预演"]


def test_complete_public_lesson_ids_keep_exact_catalog_preview(setup, monkeypatch):
    state, stages = setup
    state.step = 2
    requested = []

    def one(table, key):
        requested.append(key)
        return {"id": key, "subParameterType": "ParameterType_Dance", "mainParameter": 50,
                "subParameter": 20, "star": 10, "stamina": 8}

    monkeypatch.setattr(context, "catalog", lambda: NS(one=one))
    monkeypatch.setattr(context, "_tier_changes", lambda *a: [])
    rows = context.preview_lessons(state, [LessonOption("Vi", "Da", True)])
    assert requested == stages[1]["open_lesson_ids"]
    assert rows[0]["delta"] == {"Vi": 50, "Da": 20, "star": 10, "stamina": -8, "produce_point": 30}


def test_unknown_idol_trend_keeps_known_main_attr_sp_rule_without_fabricated_gains(setup, monkeypatch):
    from hiro.brain.deciders import ProduceDeciders
    from hiro.contracts import GameState
    state, _ = setup
    state.step = 4
    state.idol_card_id = "i_card-kllj-3-000"
    state.main_attr = "Vi"
    monkeypatch.setattr(context, "catalog", lambda: NS(one=lambda table, key: {"id": key}))
    options = [{"option": "training", "attr": a, "hp_cost": 8 if a == "Vi" else 6} for a in context.ATTRS]
    rows = context.preview_action_select(state, options)
    assert all(r["delta"] == {} and "流行顺序未知" in r["预演"] for r in rows)
    decision = ProduceDeciders(None, main_attr="Vi", idol_card_id=state.idol_card_id).decide(
        "ACTION_SELECT", GameState(produce=state.to_dict(), page_fields={"options": options}))
    assert decision.source == "rule"
    assert decision.action.args["attr"] == "Vi" and decision.action.args["sp"] is True


def test_unknown_trend_does_not_estimate_finals_gain_or_turns(setup, monkeypatch):
    from hiro.state.produce import FINALS
    state, _ = setup
    state.idol_card_id = "i_card-kllj-3-000"
    state.mode = FINALS
    assert context.r1_bonus_gain(state, {"Vi": 50}) is None
    monkeypatch.setattr(context, "catalog", lambda: None)
    monkeypatch.setattr(context, "hif_preview", lambda *a, **k: {"source": {"battle_config": {"vocal": 100, "dance": 100, "visual": 100}}})
    result = context.exam_brief(state, FINALS, 7)
    assert "流行顺序未知" in result["说明"] and "回合" not in result
