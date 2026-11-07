import copy
import json

import pytest

from tools import check_resource_horizon_scenarios as scenarios

pytestmark=pytest.mark.synthetic


def case(name):
    return next(f for f in scenarios.build_fixtures(("R",)) if f["scenario"]==name)


@pytest.mark.parametrize("name,expected",[
    ("guaranteed_next_turn","supplier"),("already_at_threshold","filler"),("final_turn","filler"),
    ("explicit_probability_half","supplier"),("explicit_probability_tenth","filler"),
])
def test_closed_arithmetic_expected_actions(name,expected):
    fixture=case(name)
    assert fixture["oracle"]["strict_action"]["card_id"]==expected
    if name=="explicit_probability_half":assert fixture["oracle"]["expected_values"]=={"supplier":4.5,"filler":2}
    if name=="explicit_probability_tenth":assert fixture["oracle"]["expected_values"]=={"supplier":.9,"filler":2}
    if name=="already_at_threshold":assert fixture["oracle"]["expected_values"]=={"supplier":9,"filler":11}
    if name=="final_turn":assert fixture["oracle"]["expected_values"]=={"supplier":0,"filler":2}


def test_unknown_probability_is_not_zero_one_or_a_strict_action():
    fixture=case("unknown_future_probability")
    oracle=fixture["oracle"]
    assert oracle["strict_action"] is None and oracle["probability_used"] is None
    assert oracle["comparison"]=={"supplier":{"constant":0,"p_coefficient":9},"filler":{"constant":2,"p_coefficient":0}}
    assert oracle["supplier_better_if_p_greater_than"]==pytest.approx(2/9)
    for slot in (0,1):assert scenarios.judge_action(fixture,{"slot":slot})["strict_action_pass"] is None


@pytest.mark.parametrize("change,coefficient",[("already_at_threshold",9),("insufficient_gain",0)])
def test_unknown_probability_equal_coefficients_cancel_without_guessing_p(change,coefficient):
    data=copy.deepcopy(case("unknown_future_probability")["model_input"])
    if change=="already_at_threshold":data["resource"]["current"]=4
    else:next(c for c in data["current_cards"] if c["id"]=="supplier")["resource_gain"]=2
    result=scenarios.oracle(data)
    assert result["status"]=="unique_action" and result["strict_action"]["card_id"]=="filler"
    assert result["probability_used"] is None and result["expected_values"] is None
    assert result["comparison"]=={"supplier":{"constant":0,"p_coefficient":coefficient},
                                  "filler":{"constant":2,"p_coefficient":coefficient}}


@pytest.mark.parametrize("name",["unknown_customized_supplier_gain","unknown_customized_target_threshold"])
def test_unknown_customized_effect_is_not_filled_with_catalog_guess(name):
    fixture=case(name)
    assert fixture["oracle"]["status"]=="no_strict_oracle_unknown_effect"
    assert fixture["oracle"]["strict_action"] is None and fixture["oracle"]["expected_values"] is None


def test_slot_swapping_and_resource_renaming_preserve_semantic_oracle():
    fixtures=scenarios.build_fixtures(("R","unrelated_name"))
    assert len(fixtures)==32
    for name in {f["scenario"] for f in fixtures}:
        group=[f for f in fixtures if f["scenario"]==name]
        semantic_actions={f["oracle"]["strict_action"]["card_id"] if f["oracle"]["strict_action"] else None for f in group}
        assert len(semantic_actions)==1
        if None not in semantic_actions:assert {f["oracle"]["strict_action"]["slot"] for f in group}=={0,1}
        for fixture in group:
            resource=fixture["model_input"]["resource"]["key"]
            assert all(c["resource_key"]==resource for c in fixture["model_input"]["current_cards"])
            assert fixture["model_input"]["next_turn_target"]["resource_key"]==resource


@pytest.mark.parametrize("path,value",[
    (("closed_assumptions","resource_decay"),1),
    (("next_turn_target","availability","probability"),.5),
    (("next_turn_target","availability","status"),"assume_guaranteed"),
    (("resource","current"),True),
])
def test_unspecified_mechanics_and_fabricated_unknown_probability_rejected(path,value):
    data=copy.deepcopy(case("unknown_future_probability")["model_input"])
    target=data
    for key in path[:-1]:target=target[key]
    target[path[-1]]=value
    with pytest.raises(ValueError):scenarios.validate_input(data)


@pytest.mark.parametrize("probability",[-.1,1.1,True,float("nan"),float("inf")])
def test_probability_validation(probability):
    data=copy.deepcopy(case("explicit_probability_half")["model_input"])
    data["next_turn_target"]["availability"]["probability"]=probability
    with pytest.raises(ValueError):scenarios.oracle(data)


def test_judge_distinguishes_illegal_wrong_and_correct_without_claiming_quality():
    fixture=case("guaranteed_next_turn")
    assert scenarios.judge_action(fixture,{"slot":0})["strict_action_pass"] is True
    assert scenarios.judge_action(fixture,{"slot":1})["strict_action_pass"] is False
    assert scenarios.judge_action(fixture,{"slot":True})["legal"] is False
    assert scenarios.judge_action(fixture,{"slot":2})["legal"] is False
    assert scenarios.judge_action(fixture,{"slot":0})["reasoning_quality"]=="not_evaluated"
    fixture["oracle"]["strict_action"]["slot"]=1
    with pytest.raises(ValueError,match="hash"):scenarios.judge_action(fixture,{"slot":1})


def test_generation_reproducible_and_output_keeps_oracle_separate(tmp_path):
    assert scenarios.build_fixtures()==scenarios.build_fixtures()
    output=tmp_path/"fixtures.json"
    assert scenarios.main(["--output",str(output)])==0
    result=json.loads(output.read_text(encoding="utf-8"))
    assert result["fixture_count"]==32 and result["model_calls"]==0 and not result["private_inputs_read"]
    for fixture in result["fixtures"]:
        assert "oracle" not in fixture["model_input"]
        assert fixture["model_input_sha256"]==scenarios._hash(fixture["model_input"])
