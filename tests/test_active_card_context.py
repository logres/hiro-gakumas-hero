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
