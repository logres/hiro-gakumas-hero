"""Public-master-only hypothetical action-refund/installed-trigger acceptance fixture.

No recorded state, screenshots, devices, model adapters, or game execution.
This exports an oracle, not a decision-engine pass or an observed score result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from hiro.brain.state import BattleState, ExamMemory
from hiro.contracts import Action
from hiro.contracts.trace import freeze_exam_decision_input, EXAM_REPLAY_FLAGS
from tools import check_mechanism_decisions as fixtures
from tools import replay_exam_choice as replay

from hiro.brain.active_card_context import _persistent
from hiro.brain.cards import description_text
from hiro.state.catalog import catalog

VERSION = "1.0"
YUME = "p_card-02-men-2_057"
LOVELY = "p_card-02-act-2_046"
FANCY = "p_card-02-men-2_058"
HIKARU = "p_card-02-act-3_050"
SPECS = {
    (YUME,1): ("ゆめみごこち+","ProduceCardCategory_MentalSkill",0,"ExamCostType_ExamReview",1,
               "好印象消費1やる気+5スキルカード使用数追加+1重複不可"),
    (LOVELY,1): ("ラブリーウインク+","ProduceCardCategory_ActiveSkill",5,"ExamCostType_Unknown",0,
                 "好印象+5好印象の80%分パラメータ上昇"),
    (FANCY,1): ("ファンシーチャーム+","ProduceCardCategory_MentalSkill",4,"ExamCostType_Unknown",0,
                "好印象+5以降、メンタルスキルカード使用時、好印象+1重複不可 レッスン中1回"),
    (HIKARU,0): ("輝くキミへ","ProduceCardCategory_ActiveSkill",0,"ExamCostType_ExamCardPlayAggressive",4,
                 "やる気消費4スキルカード使用数追加+1以降、スキルカード使用時、好印象の30%分パラメータ上昇重複不可 レッスン中1回"),
    (HIKARU,1): ("輝くキミへ+","ProduceCardCategory_ActiveSkill",0,"ExamCostType_ExamCardPlayAggressive",4,
                 "やる気消費4スキルカード使用数追加+1以降、スキルカード使用時、好印象の50%分パラメータ上昇重複不可 レッスン中1回"),
}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def _closed(row, expected, descriptive):
    semantic={k:v for k,v in row.items() if k not in descriptive}
    if semantic != expected:
        raise ValueError("Public master filter/target/schema changed: " + str(row.get("id")))


def _checked_effect(effect, effect_type, value, count):
    expected={"id":effect["id"],"effectType":effect_type,"effectValue1":value,"effectValue2":0,
        "effectCount":count,"effectTurn":0,"targetProduceCardId":"","targetUpgradeCount":0,
        "targetExamEffectType":"ProduceExamEffectType_Unknown","produceCardSearchId":"",
        "movePositionType":"ProduceCardMovePositionType_Unknown","pickRangeType":"ProducePickRangeType_Unknown",
        "pickCountReferenceProduceCardSearchId":"","pickCountType":"ProducePickCountType_Unknown",
        "pickCountMin":0,"pickCountMax":0,"produceCardSearchId2":"","pickRangeType2":"ProducePickRangeType_Unknown",
        "pickCountReferenceProduceCardSearchId2":"","pickCountType2":"ProducePickCountType_Unknown",
        "pickCountMin2":0,"pickCountMax2":0,"chainProduceExamEffectId":"","chainProduceExamEffectIds":[],
        "produceExamStatusEnchantId":"","produceCardStatusEnchantId":"","produceCardGrowEffectIds":[]}
    suffix=effect_type.removeprefix("ProduceExamEffectType_")
    names={"ExamReview":"exam_review","ExamLessonDependExamReview":"exam_lesson_depend_exam_review",
           "ExamCardPlayAggressive":"exam_card_play_aggressive","ExamPlayableValueAdd":"exam_playable_value_add"}
    expected["effectGroupIds"]=[f"effect_group-visible-{names[suffix]}-000"]
    if suffix=="ExamLessonDependExamReview":expected["effectGroupIds"].append("effect_group-visible-exam_lesson-000")
    _closed(effect,expected,{"produceDescriptions","customizeProduceDescriptions"})


def _checked_search(search,categories):
    expected={"id":search["id"],"cardRarities":[],"produceCardIds":[],"upgradeCounts":[],
        "planType":"ProducePlanType_Unknown","cardCategories":categories,
        "cardStatusType":"ProduceCardSearchStatusType_Unknown","orderType":"ProduceCardOrderType_Unknown",
        "cardPositionType":"ProduceCardPositionType_Playing","cardSearchTag":"","produceCardRandomPoolId":"",
        "limitCount":0,"staminaMinMaxType":"ConditionMinMaxType_Unknown","staminaMin":0,"staminaMax":0,
        "examEffectType":"ProduceExamEffectType_Unknown","effectGroupIds":[],"isSelf":0,
        "produceCardPoolId":"","costType":"ExamCostType_Unknown","isCustomized":0}
    _closed(search,expected,{"produceDescriptions"})


class HypotheticalPublicSource:
    def confidence(self):return "hypothetical_public_master_fixture"


def checked_definitions(master):
    """Fail closed on definition/association changes before emitting an oracle."""
    rows={}
    hashes={}
    definitions={}
    for key,expected in SPECS.items():
        row=master.card(*key)
        actual=tuple(row.get(k) for k in ("name","category","stamina","costType","costValue"))+(description_text(row.get("produceDescriptions")),)
        if (actual!=expected or row.get("id")!=key[0] or row.get("upgradeCount")!=key[1]
                or row.get("forceStamina")!=0 or row.get("playProduceExamTriggerId") not in (None,"")
                or row.get("produceCardStatusEnchantId") not in (None,"")):
            raise ValueError(f"Public master definition changed: {key}")
        rows[key]=row
        label=f"ProduceCard:{key[0]}:{key[1]}"
        hashes[label]=digest(row)
        definitions[label]={"card_id":key[0],"upgrade":key[1],"name":row["name"],
                            "catalog_text":actual[-1],"customized":False}
    for key,expected_text,expected_categories,expected_type,value in [
        ((FANCY,1),"メンタルスキルカード使用時、好印象+1",["ProduceCardCategory_MentalSkill"],"ProduceExamEffectType_ExamReview",1),
        ((HIKARU,0),"スキルカード使用時、好印象の30%分パラメータ上昇",[],"ProduceExamEffectType_ExamLessonDependExamReview",300),
        ((HIKARU,1),"スキルカード使用時、好印象の50%分パラメータ上昇",[],"ProduceExamEffectType_ExamLessonDependExamReview",500),
    ]:
        mechanisms=_persistent(master,rows[key])
        if len(mechanisms)!=1 or mechanisms[0]["active_effect_text"]!=expected_text:
            raise ValueError("Persistent mechanism changed")
        mechanism=mechanisms[0]
        trigger=master.one("ProduceExamTrigger",mechanism["trigger_id"])
        search=master.one("ProduceCardSearch",trigger["produceCardSearchId"])
        effects=[master.one("ProduceExamEffect",effect["effect_id"]) for effect in mechanism["triggered_effects"]]
        if (trigger.get("phaseTypes")!=["ProduceExamPhaseType_ExamCardPlay"]
                or trigger.get("lowerSearchCount")!=1 or trigger.get("upperSearchCount")!=0
                or any(trigger.get(k) for k in ("fieldStatusTypes","fieldStatusValues","effectTypes","phaseValues"))
                or search.get("cardCategories")!=expected_categories
                or search.get("cardPositionType")!="ProduceCardPositionType_Playing"
                or len(effects)!=1 or effects[0].get("effectType")!=expected_type
                or effects[0].get("effectValue1")!=value or effects[0].get("effectValue2")!=0):
            raise ValueError("Persistent trigger/effect association changed")
        _checked_search(search,expected_categories)
        _closed(trigger,{"id":trigger["id"],"phaseTypes":["ProduceExamPhaseType_ExamCardPlay"],
             "phaseValues":[],"fieldStatusCheckTypes":[],"fieldStatusTypes":[],"fieldStatusValues":[],
             "fieldStatusProduceCardSearchIds":[],"produceCardSearchId":search["id"],
             "upperSearchCount":0,"lowerSearchCount":1,"cardMovePositionType":"ProduceCardMovePositionType_Unknown",
             "effectTypes":[],"lessonType":"ProduceStepLessonType_Unknown"},
             {"produceDescriptions","playProduceDescriptions","playEffectProduceDescriptions"})
        _checked_effect(effects[0],expected_type,value,0 if key[0]==FANCY else 1)
        definitions[f"ProduceCard:{key[0]}:{key[1]}"]["installed_effect_only"]={
            "catalog_upgrade":key[1],**{k:mechanism[k] for k in
            ("enchant_id","active_effect_text","trigger_id","trigger_definition_text","triggered_effects")}}
        for table,row in [("ProduceExamTrigger",trigger),("ProduceCardSearch",search),*(('ProduceExamEffect',effect) for effect in effects),
                          ("ProduceExamStatusEnchant",master.one("ProduceExamStatusEnchant",mechanism["enchant_id"])),
                          ("ProduceExamEffect",master.one("ProduceExamEffect",mechanism["installation_effect_id"]))]:
            hashes[f"{table}:{row['id']}"]=digest(row)
    for cid,expected_effects in [(YUME,[("e_effect-exam_card_play_aggressive-0005","ProduceExamEffectType_ExamCardPlayAggressive",5,0),
                                        ("e_effect-exam_playable_value_add-01","ProduceExamEffectType_ExamPlayableValueAdd",0,1)]),
                                 (LOVELY,[("e_effect-exam_review-0005","ProduceExamEffectType_ExamReview",5,0),
                                          ("e_effect-exam_lesson_depend_exam_review-0800-01","ProduceExamEffectType_ExamLessonDependExamReview",800,1)])]:
        plays=rows[(cid,1)].get("playEffects")
        if plays != [{"produceExamTriggerId":"","produceExamEffectId":eid,"hideIcon":False,"isOncePlayEffect":False}
                     for eid,_,_,_ in expected_effects]:raise ValueError("Candidate play effects changed")
        for eid,typ,value,count in expected_effects:
            effect=master.one("ProduceExamEffect",eid)
            _checked_effect(effect,typ,value,count)
            hashes[f"ProduceExamEffect:{eid}"]=digest(effect)
    return definitions,hashes


def build_cases(master=None):
    definitions,hashes=checked_definitions(master or catalog())
    cases=[]
    master=master or catalog()
    for missing in (None,"fancy","hikaru"):
        for swapped in (False,True):
            hand=[{"card_id":YUME,"upgrade":1},{"card_id":LOVELY,"upgrade":1}]
            if swapped:hand.reverse()
            for slot,card in enumerate(hand):
                definition=definitions[f"ProduceCard:{card['card_id']}:{card['upgrade']}"]
                spec=SPECS[(card["card_id"],card["upgrade"])]
                card.update(slot=slot,customized=False,name=definition["name"],text=definition["catalog_text"],
                            category=spec[1],genki_cost=spec[2],extra_cost={"type":spec[3],"value":spec[4]})
            state={"provenance":"hypothetical/public_master_only/not_recorded",
                   "remaining_turns":1,"actions_left":1,"impression":20,"motivation":3,
                   "genki":20,"hp":30,"multiplier_permil":1000,"hand":hand,
                   "installed_fancy_upgrade":None if missing=="fancy" else 1,
                   "installed_hikaru_upgrade_candidates":[] if missing=="hikaru" else [0,1],
                   "hikaru_candidates_exclusive":True,"other_triggers":[],"all_customized":False,
                   "assumed_trigger_availability":"installed effects active for every relevant card use",
                   "unknown_engine_order":"No assertion of score-trigger versus card-effect ordering",
                   "no_replay_claim":"Not derived from a private run; no observed-state validity or decision-engine pass implied"}
            target=next(c for c in hand if c["card_id"]==YUME)
            follow=next(c for c in hand if c["card_id"]==LOVELY)
            oracle={"strict_applicable":missing is None,"not_applicable_reason":f"missing_{missing}_trigger" if missing else None}
            if missing is None:
                oracle.update(expected_action=f"play:{target['slot']}",expected_followup=f"play:{follow['slot']}",
                    proof={"yume_impression_net":-1+1,"yume_motivation_gain":5,"yume_actions_net":-1+1,
                           "lovely_remains_payable_genki":20-5,"extra_positive_hikaru_activation":True,
                           "exclusive_variant_proofs":[{"upgrade":g,"percent":pct,"minimum_trigger_impression":19,
                                "unrounded_extra_score_lower_bound":19*pct/100,"not_combined_with_other_variant":True}
                               for g,pct in [(0,30),(1,50)]],
                           "rationale":"After Yume the impression returns to20, one action remains, and Lovely is still payable. The same Lovely continuation is available, with one extra positive installed score trigger. Original Fancy/Hikaru play-time gains are not repeated."})
            state["installed_effect_candidates"]={
                "fancy":[] if missing=="fancy" else [definitions[f"ProduceCard:{FANCY}:1"]["installed_effect_only"]],
                "hikaru":[] if missing=="hikaru" else [definitions[f"ProduceCard:{HIKARU}:{g}"]["installed_effect_only"] for g in (0,1)]}
            battle=BattleState(exam="hypothetical",turn=1,remaining_turns=1,hp=30,max_hp=None,genki=20,
                hand=[fixtures._view(master.card(c["card_id"],c["upgrade"]),c["slot"]) for c in hand],
                motivation=3,impression=20,actions_left=1,multiplier_permil=1000,
                source="hypothetical_public_master_fixture",public_info=json.dumps(state,ensure_ascii=False))
            memory=ExamMemory("hypothetical",turn=1,last_remaining=1,actions_left=1)
            flags={key:key=="HIRO_EXPLICIT_IDOL_STATE" for key in EXAM_REPLAY_FLAGS}
            with replay._flags(flags):
                frozen=freeze_exam_decision_input(battle,memory,[Action.from_legal(a) for a in battle.legal_actions()],[],
                    advisor=SimpleNamespace(profile=None),source=HypotheticalPublicSource(),idol_card_id=None)
            replay._state(frozen["input"])
            cases.append({"source_declaration":"synthetic premises plus checked public master; no recorded battle data",
                          "master_row_sha256":dict(hashes),"frozen_input":frozen,"id":f"mental_refund_installed_triggers/{missing or 'both'}/swap-{int(swapped)}",
                          "input":state,"oracle":oracle})
    return {"schema_version":VERSION,"kind":"hypothetical_public_master_acceptance_fixture",
            "tool_version":VERSION,"tool_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "master_row_sha256":hashes,"master_definition_evidence":definitions,"cases":cases,
            "model_calls":0,"device_calls":0,"decision_engine_evaluation":"not_run",
            "limitations":"Symbolic mechanism oracle only, not a full simulator, observed battle replay, strategy learning or measured score improvement."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    result=build_cases()
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(text+"\n",encoding="utf-8")
    else:print(text)


if __name__=="__main__":main()


