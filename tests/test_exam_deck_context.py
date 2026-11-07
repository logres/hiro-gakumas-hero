import copy
import json
import os
from types import SimpleNamespace as NS

import pytest

from hiro.brain import exam_deck_context as deck_context,plan_evidence
from hiro.brain.state import ExamMemory
from hiro.contracts import GameState,Source
from hiro.defaults import exam_state
from tools import replay_exam_choice as replay

pytestmark=pytest.mark.synthetic


@pytest.fixture
def master(monkeypatch):
    class Master:
        calls=[]
        def card(self,cid,up):
            self.calls.append((cid,up))
            if cid=="missing":raise KeyError(cid)
            return {"name":cid+"+"*up,"produceDescriptions":[{"text":"やる気+3" if cid=="supply" else "やる気消費4持続効果"}],
                    "stamina":5,"forceStamina":0,"costType":"ExamCostType_ExamCardPlayAggressive" if cid=="demand" else "ExamCostType_Unknown",
                    "costValue":4 if cid=="demand" else 0,"category":"ProduceCardCategory_MentalSkill"}
    result=Master()
    monkeypatch.setattr(deck_context,"catalog",lambda:result)
    return result


def state(cards=None,*,verified=False):
    cards=cards if cards is not None else [{"card_id":"supply","upgrade":0,"customized":False},
                                           {"card_id":"demand","upgrade":1,"customized":True}]
    return GameState(produce={"deck":cards,"deck_size":len(cards) if verified else None},
        field_status={"produce.deck":"verified" if verified else "pending","produce.deck_size":"verified" if verified else "pending"},
        sources={"produce.deck":Source("screen",7)},pending_review=[] if verified else ["produce.deck","produce.deck_size"])


def test_pending_retains_positive_definitions_costs_source_and_uncertainty(master):
    result=deck_context.recorded_exam_deck_context(state())
    deck=result["deck"]
    assert result["scope"]=="produce_owned_ledger/not_current_exam_piles"
    assert deck["source"]=="screen" and deck["source_seq"]==7 and deck["field_status"]=="pending"
    assert deck["pending_review"]==["produce.deck","produce.deck_size"]
    assert not deck["complete"] and not deck["absence_claim_allowed"] and not deck["recorded_inventory_complete"]
    supply,demand=deck["observed_cards"]
    assert supply["master_effect_text"]=="やる気+3"
    assert demand["costs"]["costType"]=="ExamCostType_ExamCardPlayAggressive" and demand["costs"]["costValue"]==4
    assert demand["observed_customized"] is True and not deck["customization_effects_known"]
    assert "actual customization effects are unknown" in demand["effects_basis"]
    assert "resource_thresholds" not in json.dumps(result)


def test_even_verified_inventory_is_not_a_confirmed_exam_draw_pile(master):
    deck=deck_context.recorded_exam_deck_context(state(verified=True))["deck"]
    assert deck["recorded_inventory_complete"] and deck["versions_known"]
    assert not deck["complete"] and not deck["absence_claim_allowed"]
    assert deck["current_exam_piles_status"]=="not_established_by_owned_inventory"


def test_duplicate_copies_preserved_unknown_versions_never_become_zero(master):
    raw=[{"card_id":"supply","upgrade":0},{"card_id":"supply","upgrade":0},
         {"card_id":"demand","upgrade":None},{"card_id":"missing","upgrade":1}]
    deck=deck_context.recorded_exam_deck_context(state(raw,verified=True))["deck"]
    assert len(deck["observed_cards"])==deck["observed_count"]==4
    assert deck["observed_cards"][0]==deck["observed_cards"][1]
    assert deck["observed_cards"][2]["upgrade"] is None and deck["observed_cards"][2]["unknown"]
    assert ("demand",0) not in master.calls
    assert not deck["versions_known"] and not deck["recorded_inventory_complete"] and not deck["absence_claim_allowed"]


def test_missing_deck_count_mismatch_and_unavailable_master_keep_unknown(master,monkeypatch):
    unknown=GameState(produce={})
    assert deck_context.recorded_exam_deck_context(unknown)["deck"]["observed_cards"] is None
    mismatch=state(verified=True);mismatch.produce["deck_size"]=9
    assert not deck_context.recorded_exam_deck_context(mismatch)["deck"]["recorded_inventory_complete"]
    monkeypatch.setattr(deck_context,"catalog",lambda:(_ for _ in ()).throw(deck_context.CatalogUnavailable("none")))
    result=deck_context.recorded_exam_deck_context(state())
    assert result["master_data"]=="unavailable"
    assert all(c["unknown"] for c in result["deck"]["observed_cards"])


def test_source_default_off_then_current_session_ledger_attached(master,monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","0")
    monkeypatch.setattr(exam_state,"screen_fields",lambda *a,**kw:{})
    source=exam_state.ScreenExamStateSource()
    source.begin({"session":NS(state=state(),notes=[]),"exam":"qualify-3"})
    frame=NS(raw={"remaining_turns":4},img=None,cards=[],drinks=[],remaining=4,hp=30,genki=8)
    before,_=source.read(frame,ExamMemory("qualify-3"))
    assert deck_context.PREFIX not in (before.public_info or "")
    monkeypatch.setenv(deck_context.FLAG,"1")
    after,_=source.read(frame,ExamMemory("qualify-3"))
    attached=json.loads(after.public_info.split(deck_context.PREFIX)[1])
    assert attached["deck"]["observed_cards"][1]["costs"]["costValue"]==4


def test_plan_reconsiders_supply_demand_or_trust_changes_not_sequence_or_order(master):
    context=deck_context.recorded_exam_deck_context(state())
    current=NS(hand=[],public_info=deck_context.PREFIX+json.dumps(context))
    old=plan_evidence.stamp([{"action":"play","card":"next"}],NS(hand=[],public_info=""))
    assert plan_evidence.changed(old,current)
    bound=plan_evidence.stamp(old,current)
    context["deck"]["source_seq"]=999
    context["deck"]["observed_cards"].reverse()
    current.public_info=deck_context.PREFIX+json.dumps(context)
    assert not plan_evidence.changed(bound,current)
    context["deck"]["observed_cards"][0]["costs"]["costValue"]=6
    current.public_info=deck_context.PREFIX+json.dumps(context)
    assert plan_evidence.changed(bound,current)
    context=deck_context.recorded_exam_deck_context(state(verified=True))
    current.public_info=deck_context.PREFIX+json.dumps(context)
    assert plan_evidence.changed(bound,current)


def test_legacy_replay_new_flag_default_false_preserves_previous_defaults(monkeypatch):
    new_flags=(deck_context.FLAG,"HIRO_ACTIVE_DRINK_EFFECT_CONTEXT","HIRO_ACTIVE_CARD_EFFECT_CONTEXT",
               "HIRO_FALLBACK_EFFECT_SCORING","HIRO_PLAN_EFFECT_REVALIDATION")
    for key in new_flags:monkeypatch.setenv(key,"1")
    saved={key:False for key in replay.FLAGS if key not in new_flags};before=copy.deepcopy(saved)
    with replay._flags(saved):assert all(os.environ[key]=="0" for key in new_flags)
    assert before==saved and all(os.environ[key]=="1" for key in new_flags)
    assert "src/hiro/brain/exam_deck_context.py" in replay.VERSION_FILES
