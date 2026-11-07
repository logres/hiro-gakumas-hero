"""Read exact master audition requirements; no assessment or battle simulation.

This module is deliberately independent of AssetSource.exam_requirements(), whose
interface promises preview/calculation capabilities absent from this reader.
"""
import sqlite3

from hiro.state.catalog import CatalogUnavailable, catalog


def _identifier(value):
    return isinstance(value, str) and bool(value) and value.strip() == value


def raw_exam_requirements(idol_card_id, scenario, audition_step_type, number, *, master=None):
    """Resolve every link uniquely, including the full difficulty composite key.

    Callers must supply an exact audition step enum and number from reliable
    schedule evidence. This reader never infers them from a day or display name.
    """
    result = {
        "status": "unknown", "basis": "exact_master_references/not_live_observation",
        "query": {"idol_card_id": idol_card_id, "scenario": scenario,
                  "audition_step_type": audition_step_type, "number": number},
        "source": {}, "requirements": None, "turns": None,
        "parameter_baseline": None, "star_score_bonus_baseline": None,
        "field_semantics": {
            "requirements": "ProduceExamBattleConfig vocal/dance/visual raw configuration values",
            "turns": "ProduceExamBattleConfig.turn configured base turn count",
            "parameter_baseline": "ProduceStepAuditionDifficulty.parameterBaseLine; separate from the three attribute requirements",
            "star_score_bonus_baseline": "ProduceStepAuditionDifficulty.starScoreBonusBaseLine; separate from parameterBaseLine",
        },
        "uncertainty": "主数据关联不证明客户端版本一致或当前场次配置；不推导评定、倍率、过线分数、未来属性顺序或追加回合。",
    }
    if (not all(_identifier(v) for v in (idol_card_id, scenario, audition_step_type))
            or type(number) is not int or number < 1):
        result["reason"] = "invalid_exact_query"
        return result
    try:
        master = master if master is not None else catalog()
        idols = master.by_id("IdolCard", idol_card_id)
        if len(idols) != 1:
            result["reason"] = "idol_missing_or_ambiguous"
            return result
        difficulty_id = idols[0].get("produceStepAuditionDifficultyId")
        if not _identifier(difficulty_id):
            result["reason"] = "difficulty_reference_missing"
            return result
        result["source"].update(idol_card_id=idol_card_id, difficulty_id=difficulty_id)
        rows = [r for r in master.by_id("ProduceStepAuditionDifficulty", difficulty_id)
                if r.get("produceId") == scenario and r.get("stepType") == audition_step_type
                and type(r.get("number")) is int and r["number"] == number]
        if len(rows) != 1:
            result["reason"] = "difficulty_composite_key_missing_or_ambiguous"
            return result
        difficulty = rows[0]
        config_id = difficulty.get("produceExamBattleConfigId")
        if not _identifier(config_id):
            result["reason"] = "battle_config_reference_missing"
            return result
        configs = master.by_id("ProduceExamBattleConfig", config_id)
        if len(configs) != 1:
            result["reason"] = "battle_config_missing_or_ambiguous"
            return result
        config = configs[0]
        required = ("vocal", "dance", "visual", "turn")
        if any(type(config.get(k)) is not int or config[k] < 0 for k in required) or config["turn"] < 1:
            result["reason"] = "battle_config_fields_incomplete"
            return result
        result["source"].update(battle_config_id=config_id,
                                difficulty_key={"produceId": scenario, "stepType": audition_step_type, "number": number})
        result.update(status="resolved_master", requirements={"Vo": config["vocal"], "Da": config["dance"], "Vi": config["visual"]},
                      turns=config["turn"])
        for output, field in (("parameter_baseline", "parameterBaseLine"),
                              ("star_score_bonus_baseline", "starScoreBonusBaseLine")):
            value = difficulty.get(field)
            if type(value) is int and value >= 0:
                result[output] = value
        return result
    except (CatalogUnavailable, sqlite3.Error, OSError, KeyError, TypeError, AttributeError):
        result["reason"] = "master_unavailable_or_malformed"
        return result


def scheduled_exam_requirements(idol_card_id, scenario, stage, *, master=None):
    """Bind an explicit HIF schedule stage, not a display day, to master rows.

    Schedule exam_number selects an audition *type*. The difficulty number is a
    separate discriminator and must be uniquely discovered, never assumed to be
    the schedule exam_number (or 1).
    """
    kind = stage.get("kind") if isinstance(stage, dict) else None
    exam_number = stage.get("exam_number") if isinstance(stage, dict) else None
    step_type = None
    if scenario == "produce-007" and kind == "exam" and type(exam_number) is int:
        step_type = {1: "ProduceStepType_AuditionMid1", 2: "ProduceStepType_AuditionMid2",
                     3: "ProduceStepType_AuditionFinal"}.get(exam_number)
    elif scenario == "produce-008" and exam_number is None:
        step_type = {"round1": "ProduceStepType_AuditionMid1",
                     "round2": "ProduceStepType_AuditionFinal"}.get(kind)
    mapping = {"basis": "explicit_hif_schedule_kind_and_exam_number",
               "scenario": scenario, "stage_kind": kind, "schedule_exam_number": exam_number,
               "audition_step_type": step_type, "candidate_difficulty_numbers": []}
    result = raw_exam_requirements(idol_card_id, scenario, step_type, None, master=master)
    result["schedule_mapping"] = mapping
    result["reason"] = "schedule_stage_unresolved"
    if step_type is None or not _identifier(idol_card_id):
        return result
    try:
        master = master if master is not None else catalog()
        idols = master.by_id("IdolCard", idol_card_id)
        if len(idols) != 1 or not _identifier(idols[0].get("produceStepAuditionDifficultyId")):
            result["reason"] = "idol_or_difficulty_reference_missing_or_ambiguous"
            return result
        difficulty_id = idols[0]["produceStepAuditionDifficultyId"]
        rows = [r for r in master.by_id("ProduceStepAuditionDifficulty", difficulty_id)
                if r.get("produceId") == scenario and r.get("stepType") == step_type]
        numbers = [r.get("number") for r in rows]
        mapping["difficulty_id"] = difficulty_id
        mapping["candidate_difficulty_numbers"] = numbers
        if (not numbers or any(type(n) is not int or n < 1 for n in numbers)
                or len(set(numbers)) != 1):
            result["reason"] = "difficulty_number_missing_or_ambiguous"
            return result
        result = raw_exam_requirements(idol_card_id, scenario, step_type, numbers[0], master=master)
        result["schedule_mapping"] = mapping
        return result
    except (CatalogUnavailable, sqlite3.Error, OSError, KeyError, TypeError, AttributeError):
        result["reason"] = "master_unavailable_or_malformed"
        return result
