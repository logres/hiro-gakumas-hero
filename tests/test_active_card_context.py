import copy
import json
import os
from types import SimpleNamespace as NS

import pytest

from hiro.brain import active_card_context as active,plan_evidence
from hiro.brain.state import ExamMemory
from hiro.defaults import exam_state
from tools import replay_exam_choice as replay

pytestmark=pytest.mark.synthetic


@pytest.fixture
def master(monkeypatch):
    class Master:
        cards=[{"id":"generic-card","upgradeCount":up,"name":"generic"+"+"*up,
                "produceDescriptions":[{"text":f"initial impression+{3+up}; ongoing on mental use+1"}],
                "playEffects":[{"produceExamEffectId":"immediate"},{"produceExamEffectId":"install"}]}
               for up in (0,1)]
        rows={
            ("ProduceExamEffect","immediate"):{"produceDescriptions":[{"text":"initial+3"}]},
            ("ProduceExamEffect","install"):{"produceExamStatusEnchantId":"ongoing","effectTurn":-1,"effectCount":2},
            ("ProduceExamStatusEnchant","ongoing"):{"produceDescriptions":[{"text":"mental use: impression+1"}],
                "produceExamTriggerId":"mental-use","produceExamEffectIds":["gain"]},
            ("ProduceExamTrigger","mental-use"):{"produceDescriptions":[{"text":"mental card played"}]},
            ("ProduceExamEffect","gain"):{"effectType":"ExamReview","produceDescriptions":[{"text":"impression+1"}]},
        }
        def by_id(self,table,key):
            assert table=="ProduceCard"
            return copy.deepcopy([row for row in self.cards if row["id"]==key])
        def one(self,table,key):return copy.deepcopy(self.rows[table,key])
    result=Master()
    monkeypatch.setattr(active,"catalog",lambda:result)
    return result


def raw(slot=1):
    return {"kind":"enchant","slot":slot,"card_id":"generic-card","name":"misleading+++",
            "upgrade":9,"customized":False,"value":None,"unit":None}


def test_persistent_links_separate_initial_gain_and_keep_versions_as_alternatives(master):
    before=raw()
    result=active.observed_active_card_context([before])
    entry=result["cards"][0]
    assert entry["identity_status"]=="observed_base_card_id"
    assert entry["actual_upgrade_status"]=="unknown" and not entry["customization_effects_known"]
    assert [v["upgrade"] for v in entry["candidate_variants"]]==[0,1]
    for variant in entry["candidate_variants"]:
        effect=variant["persistent_effects"][0]
        assert effect["active_effect_text"]=="mental use: impression+1"
        assert effect["trigger_id"]=="mental-use" and effect["catalog_installation_turns"]==-1
        assert effect["catalog_installation_count"]==2
        assert effect["current_remaining_count_status"].startswith("unknown/")
        assert "initial" not in json.dumps(variant["persistent_effects"])
        assert "initial" in variant["card_definition_text"]
    assert before==raw()


def test_unknown_identity_name_history_and_non_enchant_do_not_infer(master):
    result=active.observed_active_card_context([
        {"kind":"enchant","name":"generic+++","card_id":None},
        {"kind":"enchant","name":"generic","card_id":"absent"},
        {"kind":"status","name":"generic","card_id":"generic-card"},
    ])
    assert len(result["cards"])==2 and result["ignored_non_enchant_count"]==1
    assert all(c["identity_status"]=="unknown" and not c["candidate_variants"] for c in result["cards"])
    assert active.observed_active_card_context(None)["observation_status"]=="not_available"


def test_missing_association_or_master_stays_unknown(master,monkeypatch):
    master.rows.pop(("ProduceExamTrigger","mental-use"))
    result=active.observed_active_card_context([raw()])
    assert all(v["persistent_effects_status"]=="unknown" and v["persistent_effects"]==[]
               for v in result["cards"][0]["candidate_variants"])
    monkeypatch.setattr(active,"catalog",lambda:(_ for _ in ()).throw(active.CatalogUnavailable("none")))
    result=active.observed_active_card_context([raw()])
    assert result["master_data"]=="unavailable" and not result["cards"][0]["candidate_variants"]


def test_two_observed_slots_do_not_become_verified_stack_count(master):
    result=active.observed_active_card_context([raw(1),raw(4)])
    assert len(result["cards"])==2
    assert all(c["remaining_trigger_count_status"]=="unknown" for c in result["cards"])
    assert "stack_count" not in json.dumps(result)


def test_source_reads_current_raw_ids_not_lossy_normalized_statuses(master,monkeypatch):
    monkeypatch.setenv(active.FLAG,"1")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","0")
    monkeypatch.setattr(exam_state,"screen_fields",lambda *a,**kw:{"statuses":[{"name":"generic","value":None,"type":None,"unit":"none"}]})
    source=exam_state.ScreenExamStateSource()
    source.begin({"exam":"qualify-3"})
    frame=NS(raw={"statuses":[raw()]},img=None,cards=[],drinks=[],remaining=4,hp=30,genki=8)
    state,_=source.read(frame,ExamMemory("qualify-3"))
    context=json.loads(state.public_info.split(active.PREFIX)[1])
    assert context["cards"][0]["candidate_variants"][0]["persistent_effects"]
    assert "mental use: impression+1" in json.dumps(state.to_prompt_dict())
    monkeypatch.delenv(active.FLAG)
    unchanged,_=source.read(frame,ExamMemory("qualify-3"))
    assert active.PREFIX not in (unchanged.public_info or "")


def test_plan_revalidates_new_or_changed_mechanism_but_not_slot_or_frame(master):
    context=active.observed_active_card_context([raw()])
    old=NS(hand=[],public_info="")
    plan=plan_evidence.stamp([{"action":"play","card":"candidate"}],old)
    state=NS(hand=[],public_info=active.PREFIX+json.dumps(context))
    assert plan_evidence.changed(plan,state)
    bound=plan_evidence.stamp(plan,state)
    context["cards"][0]["observed_slot"]=8
    context["cards"][0]["frame_sha256"]="new frame"
    state.public_info=active.PREFIX+json.dumps(context)
    assert not plan_evidence.changed(bound,state)
    context["cards"][0]["candidate_variants"][0]["persistent_effects"][0]["active_effect_text"]="new trigger"
    state.public_info=active.PREFIX+json.dumps(context)
    assert plan_evidence.changed(bound,state)
    state.public_info=active.PREFIX+json.dumps(active.observed_active_card_context([]))
    assert plan_evidence.changed(bound,state)


def test_legacy_flags_preserve_all_prior_defaults_and_original_input(monkeypatch):
    additions=(active.FLAG,"HIRO_PLAN_EFFECT_REVALIDATION","HIRO_FALLBACK_EFFECT_SCORING")
    for key in additions:monkeypatch.setenv(key,"1")
    saved={key:False for key in replay.FLAGS if key not in additions}
    before=copy.deepcopy(saved)
    with replay._flags(saved):
        assert all(os.environ[key]=="0" for key in additions)
    assert saved==before and all(os.environ[key]=="1" for key in additions)
    assert "src/hiro/brain/active_card_context.py" in replay.VERSION_FILES


def test_successful_commit_detail_survives_only_with_current_icon(master, monkeypatch):
    from hiro.brain.battle import BattleBrain
    from hiro.brain.rules import Decision
    from hiro.brain.state import BattleState
    from hiro.brain.cards import CardView
    monkeypatch.setenv(active.FLAG,"1")
    card=CardView(0,"generic","generic-card",1,True,"mental",0,0,None,"catalog")
    detail={"slot":0,"card_id":"generic-card","upgrade":1,"snapshot_sha256":"a"*64,
            "detail_sha256":"b"*64,"raw_ocr_lines":["actual extra effect +1"],"ocr_completeness":"partial"}
    state=BattleState(exam="qualify-3",turn=4,remaining_turns=10,hp=30,max_hp=30,genki=0,hand=[card],
        public_info="本帧卡牌详情原始证据："+json.dumps({"cards":[detail]}))
    memory=ExamMemory("qualify-3")
    assert not memory.successful_card_detail_candidates  # A decision without successful commit records nothing.
    BattleBrain(None).commit(state,memory,Decision("play:0","success","llm"))
    assert len(memory.successful_card_detail_candidates)==1
    record=memory.successful_card_detail_candidates[0]
    assert record["scope"]=="memory_lifetime_only" and record["source_trace_seq"] is None
    assert record["snapshot_sha256"]=="a"*64 and record["upgrade"]==1
    context=active.observed_active_card_context([raw()],historical_candidates=memory.successful_card_detail_candidates,exam=memory.exam)
    entry=context["cards"][0]
    assert entry["historical_detail_candidates"][0]["raw_ocr_lines"]==["actual extra effect +1"]
    assert entry["actual_upgrade_status"]=="unknown" and entry["customization_effects_known"] is False
    assert not active.observed_active_card_context([],historical_candidates=memory.successful_card_detail_candidates,exam=memory.exam)["cards"]
    mismatch=active.observed_active_card_context([raw()],historical_candidates=memory.successful_card_detail_candidates,exam="other")
    assert "historical_detail_candidates" not in mismatch["cards"][0]
    restored=ExamMemory.from_dict(json.loads(json.dumps(memory.to_dict())))
    assert not restored.successful_card_detail_candidates and restored.successful_detail_commit_ordinal==0


def test_historical_detail_source_and_plan_semantics(master,monkeypatch):
    monkeypatch.setenv(active.FLAG,"1")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","0")
    monkeypatch.setattr(exam_state,"screen_fields",lambda *a,**kw:{"statuses":[]})
    record={"exam":"qualify-3","card_id":"generic-card","upgrade":1,
            "scope":"memory_lifetime_only","status":"historical_partial/not_verified",
            "raw_ocr_lines":["extra+1"],"snapshot_sha256":"a"*64,"detail_sha256":"b"*64}
    memory=ExamMemory("qualify-3",successful_card_detail_candidates=[record])
    source=exam_state.ScreenExamStateSource();source.begin({"exam":"qualify-3"})
    frame=NS(raw={"statuses":[raw()]},img=None,cards=[],drinks=[],remaining=3,hp=30,genki=20)
    state,_=source.read(frame,memory)
    assert "extra+1" in state.to_prompt_dict()["public_info"]
    old=plan_evidence.stamp([{"action":"play","card":"next"}],state)
    record.update(snapshot_sha256="c"*64,detail_sha256="d"*64,successful_commit_ordinal=99)
    state,_=source.read(frame,memory)
    assert not plan_evidence.changed(old,state)
    record["raw_ocr_lines"]=["extra+2"]
    state,_=source.read(frame,memory)
    assert plan_evidence.changed(old,state)


def test_historical_detail_missing_or_wrong_identity_does_not_record(master,monkeypatch):
    from hiro.brain.cards import CardView
    monkeypatch.setenv(active.FLAG,"1")
    card=CardView(0,"generic","generic-card",1,True,"mental",0,0,None,"catalog")
    memory=ExamMemory("qualify-3")
    state=NS(exam="other",turn=1,hand=[card],public_info="")
    active.remember_successful_detail(state,memory,card)
    assert not memory.successful_card_detail_candidates
    state.exam=memory.exam
    state.public_info="本帧卡牌详情原始证据："+json.dumps({"cards":[{"slot":0,"card_id":"wrong","upgrade":1,
        "snapshot_sha256":"a"*64,"detail_sha256":"b"*64,"raw_ocr_lines":["extra"]}]})
    active.remember_successful_detail(state,memory,card)
    assert not memory.successful_card_detail_candidates


def test_memory_positional_turn_compatibility_and_legacy_restore():
    assert ExamMemory("qualify-3",7).turn==7
    restored=ExamMemory.from_dict({"exam":"qualify-3","turn":7})
    assert restored.turn==7 and restored.successful_card_detail_candidates==[]


@pytest.mark.parametrize("memory",[None,NS(exam="qualify-3")])
def test_source_optional_history_works_with_lightweight_memory(master,monkeypatch,memory):
    from hiro.brain.state import BattleState
    monkeypatch.setenv(active.FLAG,"1")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","0")
    monkeypatch.setenv("HIRO_EXAM_DECK_CONTEXT","0")
    monkeypatch.setattr(exam_state,"screen_fields",lambda *a,**kw:{})
    monkeypatch.setattr(exam_state,"screen_state",lambda *a,**kw:BattleState(
        exam="qualify-3",turn=1,remaining_turns=3,hp=30,max_hp=30,genki=0,hand=[]))
    source=exam_state.ScreenExamStateSource();source.begin({"exam":"qualify-3"})
    state,_=source.read(NS(raw={"statuses":[raw()]},img=None),memory)
    assert active.PREFIX in state.public_info
    assert "historical_detail_candidates" not in state.public_info
