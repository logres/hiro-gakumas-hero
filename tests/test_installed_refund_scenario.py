"""Public-master-only symbolic fixtures; no private battle input or model calls."""
import copy
import json
import pytest
from hiro.state.catalog import catalog
from tools import check_installed_refund_scenario as tool
from tools import replay_exam_choice as replay

pytestmark=pytest.mark.master


def test_public_only_frozen_inputs_and_swapped_strict_oracle():
    result=tool.build_cases()
    assert result["model_calls"]==result["device_calls"]==0
    assert result["decision_engine_evaluation"]=="not_run"
    assert len(result["cases"])==6
    positive=[c for c in result["cases"] if c["oracle"]["strict_applicable"]]
    assert [c["oracle"]["expected_action"] for c in positive]==["play:0","play:1"]
    assert [c["oracle"]["expected_followup"] for c in positive]==["play:1","play:0"]
    for case in result["cases"]:
        frozen=case["frozen_input"]
        assert frozen["schema_version"]=="1.0"
        assert frozen["sha256"]==tool.digest(frozen["input"])
        replay._state(frozen["input"])
        assert frozen["input"]["battle_state"]["source"]=="hypothetical_public_master_fixture"
        assert frozen["input"]["source_confidence"]=="hypothetical_public_master_fixture"
        assert frozen["input"]["idol_card_id"] is None
        assert case["master_row_sha256"]==result["master_row_sha256"]
        assert all(len(value)==64 for value in case["master_row_sha256"].values())
        assert "hypothetical" in case["input"]["provenance"]
    for case in positive:
        proof=case["oracle"]["proof"]
        assert proof["yume_impression_net"]==0 and proof["yume_actions_net"]==0
        assert [p["percent"] for p in proof["exclusive_variant_proofs"]]==[30,50]
        assert all(p["unrounded_extra_score_lower_bound"]>0 for p in proof["exclusive_variant_proofs"])


def test_missing_trigger_cases_have_no_strict_choice_claim():
    cases=tool.build_cases()["cases"]
    negative=[c for c in cases if not c["oracle"]["strict_applicable"]]
    assert len(negative)==4
    for case in negative:
        assert "expected_action" not in case["oracle"]
        assert "expected_followup" not in case["oracle"]
        assert case["oracle"]["not_applicable_reason"] in ["missing_fancy_trigger","missing_hikaru_trigger"]


@pytest.mark.parametrize("table,mutation",[
    ("ProduceCardSearch",lambda r:r.update(isSelf=1)),
    ("ProduceCardSearch",lambda r:r.update(newRestriction=True)),
    ("ProduceExamTrigger",lambda r:r.update(fieldStatusCheckTypes=["new_condition"])),
    ("ProduceExamEffect",lambda r:r.update(chainProduceExamEffectId="extra_effect")),
    ("ProduceExamEffect",lambda r:r.update(targetProduceCardId="redirect")),
])
def test_added_hidden_conditions_reject_oracle(table,mutation):
    base=catalog()
    class Altered:
        def card(self,*args):return base.card(*args)
        def one(self,name,key):
            row=copy.deepcopy(base.one(name,key))
            if name==table:mutation(row)
            return row
    with pytest.raises(ValueError):tool.build_cases(Altered())
