"""Synthetic oracles and real pipeline wiring; mock calls are never quality."""
import copy
import hashlib
import json

import pytest
from hiro.brain.llm import LLMResult
from hiro.contracts import Action
from tools import check_synthetic_generic_decisions as check

pytestmark=pytest.mark.synthetic


def correct(case):
    hand=case["frozen"]["input"]["battle_state"]["hand"]
    oracle=case["oracle"]
    chosen=next(c for c in hand if c["card_id"]==oracle["expected_card_id"])
    follow=next((c for c in hand if c["card_id"]==oracle["expected_followup_card_id"]),None)
    return {"action":Action.play_card(chosen["slot"]).to_dict(),
            "plan":[{"action":"play","card":follow["name"]}] if follow else []}


def test_cases_use_real_frozen_contract_without_master_or_private_data():
    cases=check.build_cases()
    assert len(cases)==28
    assert {c["group"] for c in cases}=={"instant","settlement_cost","refund_resource","horizon"}
    for case in cases:
        payload=case["frozen"]["input"]
        state,memory,*_=check.replay._state(payload)
        with check.replay._flags(payload["flags"]):
            assert state.to_prompt_dict()==case["prompt_input"]
        assert check._hash(payload)==case["frozen"]["sha256"]
        assert check._hash(case["oracle"])==case["oracle_sha256"]
        assert set(payload["flags"])==set(check.EXAM_REPLAY_FLAGS)
        assert payload["profile"] is None and payload["idol_card_id"] is None
        assert "oracle" not in payload and "expected_card_id" not in json.dumps(case["prompt_input"])
        assert check.judge(correct(case),case)["criterion_pass"]


def test_slot_and_label_transform_preserves_semantic_oracle():
    groups={}
    for case in check.build_cases():groups.setdefault((case["group"],case["parameter"]),[]).append(case)
    for variants in groups.values():
        assert len(variants)==4
        assert len({c["oracle_sha256"] for c in variants})==1
        assert len({c["frozen"]["sha256"] for c in variants})==4
        assert {c["transform"]["label"] for c in variants}=={"A","B"}


def test_cost_resource_and_horizon_reversals_are_strict_closed_arithmetic():
    cases=[c for c in check.build_cases() if c["transform"]=={"label":"A","swapped":False}]
    def get(group,p):return next(c for c in cases if c["group"]==group and c["parameter"]==p)
    assert get("settlement_cost",0)["oracle"]["totals"]=={"a":30,"b":26,"skip":20}
    assert get("settlement_cost",10)["oracle"]["totals"]=={"a":20,"b":26,"skip":20}
    assert get("horizon",1)["oracle"]["expected_card_id"]=="synthetic-a"
    assert get("horizon",3)["oracle"]["expected_card_id"]=="synthetic-b"
    assert get("horizon",3)["assumptions"]["future_legal_actions"]==["skip"]
    negative=get("refund_resource",2)
    assert "play:0" not in {Action.from_dict(a).legal_key() for a in negative["frozen"]["input"]["legal"]}


def test_oracle_requires_exact_followup_and_rejects_position_bias():
    case=next(c for c in check.build_cases() if c["group"]=="refund_resource" and c["parameter"]==3)
    reply=correct(case)
    reply["plan"]*=2
    assert not check.judge(reply,case)["criterion_pass"]
    reply["plan"]=[]
    assert not check.judge(reply,case)["criterion_pass"]
    case=next(c for c in check.build_cases() if c["group"]=="instant" and c["transform"]["swapped"])
    assert not check.judge({"action":Action.play_card(0).to_dict()},case)["criterion_pass"]


def test_default_offline_and_versions_are_auditable(monkeypatch):
    monkeypatch.setattr(check,"from_spec",lambda _:pytest.fail("offline must not construct adapter"))
    case=check.build_cases()[0]
    report=check.run(case_ids=[case["id"]])
    assert report["model_calls_used"]==0 and report["max_model_calls"]==0
    assert report["cases"][0]["direct_model_checks"] is None
    assert report["cases"][0]["model_quality_status"]=="not_measured"
    assert not report["sources_changed_during_run"]
    assert "src/hiro/brain/prompts/exam_generic.md" in report["versions_start"]["sha256_by_file"]


def test_mock_adapter_uses_real_generic_prompt_without_claiming_quality(monkeypatch):
    case=check.build_cases()[0];seen=[]
    class Mock:
        name="mock";model="synthetic"
        def ask_json(self,system,user):
            seen.append((system,user))
            return LLMResult({"action":"play:0","reason":"test wiring","plan":[]},"test",0,adapter=self.name,model=self.model)
    monkeypatch.setattr(check,"from_spec",lambda _:Mock())
    report=check.run(adapter="codex",max_model_calls=1,case_ids=[case["id"]])
    result=report["cases"][0]
    assert report["model_calls_used"]==len(seen)==1
    assert "null 本身不证明永久" in seen[0][0]
    assert "合成A甲" in seen[0][1]
    assert result["model_quality_status"]=="mock_adapter_not_quality"
    assert result["direct_model_checks"] is None
    assert result["pipeline_checks"] is not None


def test_guarded_attempt_preserves_evidence_and_is_not_direct_model(monkeypatch):
    case=check.build_cases()[0]
    class FakeRealProtocol:
        name="codex-cli";model="test-only"
        def ask_json(self,*args):return LLMResult({},"invalid evidence",0,adapter=self.name,model=self.model)
    monkeypatch.setattr(check,"from_spec",lambda _:FakeRealProtocol())
    def decide(payload,adapter=None):
        result=correct(case);result["source"]="fallback";result["llm"]=[]
        if adapter:
            reply=adapter.ask_json("synthetic","synthetic")
            result["llm"]=[{"raw":reply.raw}]
        return result
    monkeypatch.setattr(check.replay,"_decide",decide)
    report=check.run(adapter="codex",max_model_calls=1,case_ids=[case["id"]])
    result=report["cases"][0]
    assert result["model_quality_status"]=="model_attempted_guarded"
    assert result["direct_model_checks"] is None and result["pipeline_checks"]["criterion_pass"]
    assert result["model_call_evidence"]==[{"raw":"invalid evidence"}]


@pytest.mark.parametrize("kwargs",[{"adapter":"codex"},{"max_model_calls":-1},{"case_ids":["missing"]}])
def test_bad_options_rejected_before_model(kwargs):
    with pytest.raises(ValueError):check.run(**kwargs)


def test_multiple_calls_never_hide_wrong_first_choice(monkeypatch):
    case=check.build_cases()[0]
    class Adapter:
        name="codex-cli";model="test-only"
        def ask_json(self,*args):return LLMResult({},"unused",0,adapter=self.name,model=self.model)
    monkeypatch.setattr(check,"from_spec",lambda _:Adapter())
    def decide(payload,adapter=None):
        result=correct(case);result.update(source="llm",llm=[])
        if adapter:
            adapter.ask_json("synthetic","synthetic");adapter.ask_json("synthetic","synthetic")
            result["llm"]=[{"raw":json.dumps({"action":"play:1","plan":[]}),"error":"guard rejected"},
                           {"raw":json.dumps({"action":"play:0","plan":[]}),"error":None}]
        return result
    monkeypatch.setattr(check.replay,"_decide",decide)
    report=check.run(adapter="codex",max_model_calls=2,case_ids=[case["id"]])
    result=report["cases"][0]
    assert result["model_quality_status"]=="model_requeried/final_pipeline_only"
    assert result["direct_model_checks"] is None
    assert not result["first_model_checks"]["criterion_pass"]
    assert result["pipeline_checks"]["criterion_pass"]
    assert len(result["model_call_evidence"])==2
    assert result["first_model_choice"]["error"]=="guard rejected"
