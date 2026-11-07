"""Public, closed synthetic cases through the actual generic exam decision path.

No game data, private traces, device access, or game simulator. Default is offline.
Strict arithmetic oracles apply only under each explicitly closed premise.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hiro.brain.cards import CardView,parse_tags
from hiro.brain.llm import from_spec
from hiro.brain.state import BattleState,ExamMemory
from hiro.contracts import Action
from hiro.contracts.trace import EXAM_REPLAY_FLAGS,freeze_exam_decision_input
from hiro.defaults.advisor import RuleLLMAdvisor
from tools import replay_exam_choice as replay

SCOPE="closed_public_synthetic/real_generic_pipeline/not_game_simulator"


def _hash(value):
    return hashlib.sha256(replay._canonical(value)).hexdigest()


class SyntheticSource:
    def confidence(self):return "closed_public_synthetic"


def _card(role,slot,label,text,badge=None,extra=None,available=True):
    name=f"合成{label}{'甲' if role=='a' else '乙'}"
    return CardView(slot,name,f"synthetic-{role}",0,available,"mental" if '追加' in text else "active",
                    0,0,extra,text,parse_tags(name,text),badge)


def build_cases():
    cases=[]
    specs=[("instant",None),("settlement_cost",0),("settlement_cost",10),
           ("refund_resource",3),("refund_resource",2),("horizon",1),("horizon",3)]
    flags={key:key=="HIRO_EXPLICIT_IDOL_STATE" for key in EXAM_REPLAY_FLAGS}
    for group,parameter in specs:
        for label in ("A","B"):
            for swapped in (False,True):
                assumptions={"scope":SCOPE,"synthetic_role_display_label":label,
                    "all_effects_and_costs_are_exact_in_this_fixture":True,"no_customizations":True,
                    "other_triggers":[],"items":[],"drinks":[],"unknowns":[],
                    "multiplier_permil":1000,"concentration":0,"good_condition":0,
                    "impression_settlement":"turn_end_score_equals_remaining_impression",
                    "warning":"人工封闭假设，不证明真实游戏可达或规则全覆盖；标签不含机制信息。"}
                impression=0;motivation=0;remaining=1;followup=None
                if group=="instant":
                    a=_card('a',0,label,"パラメータ+10",10)
                    b=_card('b',1,label,"パラメータ+6",6)
                    expected='synthetic-a';totals={"a":10,"b":6,"skip":0}
                    proof="仅1行动且末回合，无触发和资源影响：10>6>0。"
                elif group=="settlement_cost":
                    impression=20
                    a=_card('a',0,label,f"好印象消費{parameter}パラメータ+10",10,
                        {"type":"ExamCostType_ExamReview","value":parameter})
                    b=_card('b',1,label,"パラメータ+6",6)
                    totals={"a":10+20-parameter,"b":26,"skip":20}
                    expected='synthetic-a' if parameter==0 else 'synthetic-b'
                    assumptions["badges_are_immediate_scores_after_payment"]=True
                    proof=f"A=10+20-{parameter}={totals['a']}；B=6+20=26；skip=20。"
                elif group=="refund_resource":
                    motivation=parameter;impression=10
                    a=_card('a',0,label,"やる気消費3好印象+5スキルカード使用数追加+1",0,
                        {"type":"ExamCostType_ExamCardPlayAggressive","value":3},parameter>=3)
                    b=_card('b',1,label,"好印象の100%分パラメータ上昇",10)
                    assumptions["refund_does_not_end_turn"]=True
                    assumptions["cash_badge_recomputed_after_setup"]=15
                    totals={"a_then_b":30 if parameter>=3 else None,"b":20,"skip":10}
                    expected='synthetic-a' if parameter>=3 else 'synthetic-b'
                    followup='synthetic-b' if parameter>=3 else None
                    proof="资源够时辅助后兑现15+结算15=30>直接10+结算10=20；不足时辅助明确不可用。"
                else:
                    remaining=parameter
                    a=_card('a',0,label,"パラメータ+8",8)
                    b=_card('b',1,label,"以降、ターン終了時、固定スコア+5",0)
                    assumptions.update(future_legal_actions=["skip"],current_cards_unavailable_after_this_turn=True,
                        persistent_tick="fixed score+5 at every turn end including this turn, never expires",
                        no_other_future_rewards=True)
                    totals={"a":8,"b":5*parameter,"skip":0}
                    expected='synthetic-a' if parameter==1 else 'synthetic-b'
                    proof=f"封闭未来仅skip，B结算{parameter}次：5*{parameter}={5*parameter}，与A的8比较。"
                hand=[a,b]
                if swapped:
                    hand.reverse()
                    for i,card in enumerate(hand):card.slot=i
                state=BattleState("synthetic-exam",1,remaining,30,30,0,hand,motivation=motivation,
                    impression=impression,score=0,actions_left=1,multiplier_permil=1000,item_charges_left=0,
                    public_info="人工封闭验收前提："+json.dumps(assumptions,ensure_ascii=False),source=SCOPE)
                memory=ExamMemory("synthetic-exam",turn=1,last_remaining=remaining,actions_left=1)
                advisor=RuleLLMAdvisor.__new__(RuleLLMAdvisor);advisor.profile=None
                with replay._flags(flags):
                    frozen=freeze_exam_decision_input(state,memory,[Action.from_legal(x) for x in state.legal_actions()],[],
                        advisor=advisor,source=SyntheticSource(),idol_card_id=None)
                    prompt=state.to_prompt_dict()
                replay._state(frozen["input"])
                oracle={"expected_card_id":expected,"expected_followup_card_id":followup,
                        "strict_under_closed_assumptions":True,"totals":totals,"proof":proof}
                cases.append({"id":f"{group}/{parameter}/label-{label}/swap-{int(swapped)}","group":group,
                    "parameter":parameter,"transform":{"label":label,"swapped":swapped},"assumptions":assumptions,
                    "frozen":frozen,"prompt_input":prompt,"prompt_input_sha256":_hash(prompt),
                    "oracle":oracle,"oracle_sha256":_hash(oracle)})
    return cases


def judge(decision,case):
    if decision is None:return None
    hand=case["frozen"]["input"]["battle_state"]["hand"]
    key=Action.from_dict(decision["action"]).legal_key()
    legal={Action.from_dict(x).legal_key() for x in case["frozen"]["input"]["legal"]}
    card=next((c for c in hand if key==f"play:{c['slot']}"),{})
    expected=case["oracle"]["expected_followup_card_id"]
    target=next((c["name"] for c in hand if c["card_id"]==expected),None)
    plan=decision.get("plan") or []
    plan_ok=(len(plan)==1 and isinstance(plan[0],dict) and plan[0].get("action")=="play"
             and plan[0].get("card")==target) if expected else not plan
    correct=card.get("card_id")==case["oracle"]["expected_card_id"]
    return {"legal":key in legal,"expected_card":correct,"required_plan":plan_ok,
            "criterion_pass":key in legal and correct and plan_ok}


def first_model_choice(evidence):
    """First raw reply only; never substitute a later corrected answer."""
    if not evidence:
        return None
    record=evidence[0]
    result={"raw":record.get("raw"),"error":record.get("error"),"decision":None}
    try:
        parsed=json.loads(record.get("raw") or "")
        action=parsed.get("action") if isinstance(parsed,dict) else None
        if not isinstance(action,str):
            raise ValueError("first response has no action string")
        result["decision"]={"action":Action.from_legal(action).to_dict(),"plan":parsed.get("plan") or []}
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        result["parse_error"]=str(exc)
    return result


def _versions():
    result=replay._versions()
    result["sha256_by_file"]["tools/check_synthetic_generic_decisions.py"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def run(*,adapter=None,max_model_calls=0,case_ids=None):
    if type(max_model_calls) is not int or not 0<=max_model_calls<=100:raise ValueError("cap must be 0..100")
    if adapter and max_model_calls==0:raise ValueError("adapter requires explicit positive global cap")
    if adapter and not(adapter=="codex" or adapter.startswith("codex:") or adapter.startswith("openai:")):
        raise ValueError("adapter must be codex[:model] or openai:model")
    cases=build_cases()
    if case_ids:
        unknown=set(case_ids)-{c["id"] for c in cases}
        if unknown:raise ValueError(f"unknown cases: {sorted(unknown)}")
        cases=[c for c in cases if c["id"] in case_ids]
    versions=_versions();capped=replay.CappedAdapter(from_spec(adapter),max_model_calls) if adapter else None
    results=[]
    for case in cases:
        payload=case["frozen"]["input"]
        with replay._flags(payload["flags"]):
            baseline=replay._decide(copy.deepcopy(payload))
            before=capped.used if capped else 0
            model=replay._decide(copy.deepcopy(payload),capped) if capped and capped.used<max_model_calls else None
            used=capped.used-before if capped else 0
        real=bool(capped and capped.name in ("codex-cli","openai"))
        direct=bool(used==1 and real and model and model.get("source")=="llm")
        status=("mock_adapter_not_quality" if used and not real else
                "direct_model" if direct else "model_requeried/final_pipeline_only" if used>1 and model and model.get("source")=="llm"
                else "model_attempted_guarded" if used else "not_measured")
        evidence=copy.deepcopy(model.get("llm") or []) if model and used else []
        first=first_model_choice(evidence)
        first_checks=judge(first["decision"],case) if first and first["decision"] else None
        results.append({**case,"rule_baseline":baseline,"rule_checks":judge(baseline,case),
            "model_decision":model,"model_calls_used":used,"model_quality_status":status,
            "direct_model_checks":judge(model,case) if direct else None,
            "pipeline_checks":judge(model,case) if used else None,
            "first_model_choice":first,"first_model_checks":first_checks if used and real else None,
            "model_call_evidence":evidence})
    end=_versions()
    return {"scope":SCOPE,"cases":results,"max_model_calls":max_model_calls,"model_calls_used":capped.used if capped else 0,
            "versions_start":versions,"versions_end":end,"sources_changed_during_run":versions!=end,
            "limits":["封闭合成算术判据，不是游戏模拟器或真实考试成绩证明。",
                      "规则/mock/guard纠正不计direct model通过；未来可用性在期限案例中是显式人工假设。"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter");parser.add_argument("--max-model-calls",type=int,default=0)
    parser.add_argument("--case",action="append",dest="cases");parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    report=run(adapter=args.adapter,max_model_calls=args.max_model_calls,case_ids=args.cases)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"cases":len(report["cases"]),"model_calls_used":report["model_calls_used"],"output":str(args.output)}))
    return 0


if __name__=="__main__":raise SystemExit(main())
