import copy
import sqlite3

import pytest

from hiro.state.catalog import Catalog
from hiro.state.exam_requirements_context import raw_exam_requirements, scheduled_exam_requirements

pytestmark = pytest.mark.synthetic


class Master:
    def __init__(self):
        self.data = {
            "IdolCard": [{"id": "idol-a", "produceStepAuditionDifficultyId": "diff-a"},
                         {"id": "idol-b", "produceStepAuditionDifficultyId": "diff-b"}],
            "ProduceStepAuditionDifficulty": [], "ProduceExamBattleConfig": []}
        for suffix, values in (("a", (101, 202, 303)), ("b", (303, 101, 202))):
            self.data["ProduceStepAuditionDifficulty"].append({
                "id": "diff-" + suffix, "produceId": "scenario", "stepType": "ProduceStepType_AuditionMid1",
                "number": 1, "produceExamBattleConfigId": "config-" + suffix,
                "parameterBaseLine": 150, "starScoreBonusBaseLine": 50})
            self.data["ProduceExamBattleConfig"].append({"id": "config-" + suffix,
                "turn": 10, **dict(zip(("vocal", "dance", "visual"), values))})

    def by_id(self, table, key):
        return [copy.deepcopy(r) for r in self.data[table] if r["id"] == key]


def query(master, **overrides):
    args = {"idol_card_id": "idol-a", "scenario": "scenario",
            "audition_step_type": "ProduceStepType_AuditionMid1", "number": 1}
    args.update(overrides)
    return raw_exam_requirements(**args, master=master)


def test_exact_identity_variants_keep_raw_field_semantics():
    master = Master(); before = copy.deepcopy(master.data)
    a, b = query(master), query(master, idol_card_id="idol-b")
    assert a["requirements"] == {"Vo": 101, "Da": 202, "Vi": 303}
    assert b["requirements"] == {"Vo": 303, "Da": 101, "Vi": 202}
    assert a["status"] == "resolved_master" and a["turns"] == 10
    assert a["parameter_baseline"] == 150 and a["star_score_bonus_baseline"] == 50
    assert a["source"]["battle_config_id"] == "config-a"
    assert not {"multiplier", "passing_score", "turn_order", "assessment"}.intersection(a)
    assert master.data == before


@pytest.mark.parametrize("overrides", [{"idol_card_id": "idol"}, {"scenario": "other"},
    {"audition_step_type": "ProduceStepType_AuditionMid2"}, {"number": 2},
    {"number": True}, {"number": 0}, {"scenario": " scenario"}])
def test_wrong_stage_or_nonexact_query_never_falls_back(overrides):
    result = query(Master(), **overrides)
    assert result["status"] == "unknown" and result["requirements"] is None


@pytest.mark.parametrize("table", ["IdolCard", "ProduceStepAuditionDifficulty", "ProduceExamBattleConfig"])
@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_every_link_requires_exactly_one_row(table, mutation):
    master = Master()
    if mutation == "missing":
        master.data[table].pop(0)
    else:
        master.data[table].append(copy.deepcopy(master.data[table][0]))
    assert query(master)["status"] == "unknown"


def test_difficulty_id_reuse_in_other_scenarios_is_not_ambiguity():
    master = Master()
    other = copy.deepcopy(master.data["ProduceStepAuditionDifficulty"][0])
    other["produceId"] = "other"
    master.data["ProduceStepAuditionDifficulty"].append(other)
    assert query(master)["status"] == "resolved_master"


@pytest.mark.parametrize("field,value", [("vocal", None), ("dance", -1), ("turn", 0), ("visual", True)])
def test_invalid_required_config_fields_stay_unknown(field, value):
    master = Master(); master.data["ProduceExamBattleConfig"][0][field] = value
    assert query(master)["requirements"] is None


def test_optional_baselines_do_not_become_zero_or_alias_requirements():
    master = Master(); row = master.data["ProduceStepAuditionDifficulty"][0]
    row.pop("parameterBaseLine"); row["starScoreBonusBaseLine"] = None
    result = query(master)
    assert result["status"] == "resolved_master"
    assert result["parameter_baseline"] is None and result["star_score_bonus_baseline"] is None


def test_catalog_sqlite_schema_error_returns_unknown():
    result = query(Catalog(sqlite3.connect(":memory:")))
    assert result["status"] == "unknown" and result["reason"] == "master_unavailable_or_malformed"


@pytest.mark.parametrize("scenario,stage,step_type", [
    ("produce-007", {"kind": "exam", "exam_number": 1}, "ProduceStepType_AuditionMid1"),
    ("produce-007", {"kind": "exam", "exam_number": 2}, "ProduceStepType_AuditionMid2"),
    ("produce-007", {"kind": "exam", "exam_number": 3}, "ProduceStepType_AuditionFinal"),
    ("produce-008", {"kind": "round1"}, "ProduceStepType_AuditionMid1"),
    ("produce-008", {"kind": "round2"}, "ProduceStepType_AuditionFinal"),
])
def test_hif_schedule_type_mapping_discovers_independent_number(scenario, stage, step_type):
    master = Master()
    row = master.data["ProduceStepAuditionDifficulty"][0]
    row.update(produceId=scenario, stepType=step_type, number=7)
    result = scheduled_exam_requirements("idol-a", scenario, stage, master=master)
    assert result["status"] == "resolved_master"
    assert result["query"]["number"] == 7  # Neither schedule index nor hardcoded 1.
    assert result["schedule_mapping"]["candidate_difficulty_numbers"] == [7]
    assert result["schedule_mapping"]["audition_step_type"] == step_type


@pytest.mark.parametrize("scenario,stage", [
    ("produce-001", {"kind": "exam", "exam_number": 1}),
    ("produce-007", {"kind": "round1"}), ("produce-008", {"kind": "exam", "exam_number": 1}),
    ("produce-007", {"kind": "exam", "exam_number": True}),
    ("produce-007", {"kind": "exam", "exam_number": 4}),
    ("produce-007", {"kind": "choice", "exam_number": 1}),
    ("produce-008", {"kind": "round2", "exam_number": 2}),
    ("produce-007", {"day": 7}), ("produce-007", None),
])
def test_unreliable_schedule_never_guesses_by_day_or_other_scenario(scenario, stage):
    result = scheduled_exam_requirements("idol-a", scenario, stage, master=Master())
    assert result["status"] == "unknown" and result["requirements"] is None


@pytest.mark.parametrize("number", [2, None, True, 1])
def test_multiple_or_invalid_difficulty_numbers_never_choose_first(number):
    master = Master()
    row = master.data["ProduceStepAuditionDifficulty"][0]
    row["produceId"] = "produce-007"
    duplicate = copy.deepcopy(row); duplicate["number"] = number
    master.data["ProduceStepAuditionDifficulty"].append(duplicate)
    result = scheduled_exam_requirements("idol-a", "produce-007", {"kind": "exam", "exam_number": 1}, master=master)
    assert result["status"] == "unknown"
    assert result["schedule_mapping"]["candidate_difficulty_numbers"] == [1, number]
