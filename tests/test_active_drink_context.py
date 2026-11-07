import copy
import json
import os
from types import SimpleNamespace as NS

import pytest

from hiro.brain import active_drink_context as active,plan_evidence
from hiro.brain.state import ExamMemory
from hiro.defaults import exam_state
from tools import replay_exam_choice as replay

pytestmark=pytest.mark.synthetic


@pytest.fixture
def master(monkeypatch):
    class Master:
        drinks=[{"id":did,"assetId":"shared-cup","name":did,
                 "produceDescriptions":[{"text":"initial genki+9; end turn impression+1"}],
                 "produceDrinkEffectIds":["initial-drink","install-drink"]} for did in ("drink-a","drink-b")]
        data={
            ("ProduceDrinkEffect","initial-drink"):{"produceExamEffectId":"initial"},
            ("ProduceDrinkEffect","install-drink"):{"produceExamEffectId":"install"},
            ("ProduceExamEffect","initial"):{"produceDescriptions":[{"text":"initial genki+9"}]},
            ("ProduceExamEffect","install"):{"produceExamStatusEnchantId":"enchant","effectTurn":-1,"effectCount":2},
            ("ProduceExamStatusEnchant","enchant"):{"produceExamTriggerId":"turn-end",
                "produceDescriptions":[{"text":"turn end: impression+1"}],"produceExamEffectIds":["gain"]},
            ("ProduceExamTrigger","turn-end"):{"produceDescriptions":[{"text":"turn end"}]},
            ("ProduceExamEffect","gain"):{"effectType":"ExamReview","produceDescriptions":[{"text":"impression+1"}]},
        }
        def rows(self,table):
            assert table=="ProduceDrink"
            return copy.deepcopy(self.drinks)
        def one(self,table,key):return copy.deepcopy(self.data[table,key])
    result=Master()
    monkeypatch.setattr(active,"catalog",lambda:result)
    return result


def raw(slot=1):
    return {"slot":slot,"kind":"drink_enchant","observed_asset":"shared-cup","score":.81,"margin":.32,
            "value":None,"unit":None,"identity_basis":"masked_drink_asset_candidate",
            "identity_status":"visual_asset_candidate","actual_source_version":"unknown"}


def test_public_chain_keeps_asset_candidates_and_separates_immediate_from_recurring(master):
    result=active.observed_active_drink_context([raw()])
    observed=result["drinks"][0]
    assert observed["identity_status"]=="visual_asset_candidate"
    assert observed["actual_source_version"]==observed["actual_modifications_status"]=="unknown"
    assert [v["drink_id"] for v in observed["candidate_variants"]]==["drink-a","drink-b"]
    for candidate in observed["candidate_variants"]:
        assert len(candidate["drink_effect_associations"])==2
        assert candidate["persistent_effects_status"]=="verified_catalog_associations"
        recurring=candidate["persistent_effects"][0]
        assert recurring["active_effect_text"]=="turn end: impression+1"
        assert recurring["trigger_id"]=="turn-end"
        assert recurring["catalog_installation_count"]==2 and recurring["catalog_installation_turns"]==-1
        assert recurring["current_remaining_count_status"].startswith("unknown/")
        assert "initial" not in json.dumps(candidate["persistent_effects"])
        assert "initial" in candidate["drink_definition_text"]


def test_unknown_asset_no_history_or_name_inference_and_other_kind_ignored(master):
    result=active.observed_active_drink_context([
        {**raw(),"observed_asset":"absent","name":"drink-a","drink_id":"drink-a","history":["drank drink-a"]},
        {**raw(),"observed_asset":None},
        {**raw(),"kind":"enchant"},
    ])
    assert len(result["drinks"])==2 and result["ignored_other_kind_count"]==1
    assert all(not d["candidate_variants"] and d["master_lookup_status"]=="unknown" for d in result["drinks"])
    assert active.observed_active_drink_context(None)["observation_status"]=="not_available"


def test_missing_chain_or_master_never_promotes_full_drink_text(master,monkeypatch):
    master.data.pop(("ProduceDrinkEffect","install-drink"))
    result=active.observed_active_drink_context([raw()])
    assert all(v["persistent_effects_status"]=="unknown" and not v["persistent_effects"]
               for v in result["drinks"][0]["candidate_variants"])
    monkeypatch.setattr(active,"catalog",lambda:(_ for _ in ()).throw(active._MISSING[0]("none")))
    result=active.observed_active_drink_context([raw()])
    assert result["master_data"]=="unavailable" and not result["drinks"][0]["candidate_variants"]


def test_multiple_icons_do_not_prove_stack_count(master):
    result=active.observed_active_drink_context([raw(1),raw(3)])
    assert len(result["drinks"])==2 and "stack_count" not in json.dumps(result)
    assert all(d["remaining_trigger_count_status"]=="unknown" for d in result["drinks"])


def test_source_uses_current_raw_asset_not_normalized_names(master,monkeypatch):
    monkeypatch.setenv(active.FLAG,"1")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","0")
    monkeypatch.setattr(exam_state,"screen_fields",lambda *a,**kw:{"statuses":[]})
    source=exam_state.ScreenExamStateSource()
    source.begin({"exam":"qualify-3"})
    frame=NS(raw={"statuses":[raw()]},img=None,cards=[],drinks=[],remaining=3,hp=30,genki=20)
    state,_=source.read(frame,ExamMemory("qualify-3"))
    context=json.loads(state.public_info.split(active.PREFIX)[1])
    assert context["drinks"][0]["candidate_variants"][0]["persistent_effects"]
    assert "turn end: impression+1" in json.dumps(state.to_prompt_dict())
    monkeypatch.delenv(active.FLAG)
    state,_=source.read(frame,ExamMemory("qualify-3"))
    assert active.PREFIX not in (state.public_info or "")


def test_plan_revalidates_mechanism_changes_but_not_slot_hash_or_visual_scores(master):
    context=active.observed_active_drink_context([raw()])
    state=NS(hand=[],public_info=active.PREFIX+json.dumps(context))
    old=plan_evidence.stamp([{"action":"play","card":"next"}],NS(hand=[],public_info=""))
    assert plan_evidence.changed(old,state)
    bound=plan_evidence.stamp(old,state)
    context["drinks"][0].update(observed_slot=5,visual_score=.9,visual_margin=.4,frame_sha256="new")
    state.public_info=active.PREFIX+json.dumps(context)
    assert not plan_evidence.changed(bound,state)
    context["drinks"][0]["candidate_variants"][0]["persistent_effects"][0]["active_effect_text"]="new"
    state.public_info=active.PREFIX+json.dumps(context)
    assert plan_evidence.changed(bound,state)
    state.public_info=active.PREFIX+json.dumps(active.observed_active_drink_context([]))
    assert plan_evidence.changed(bound,state)


def test_legacy_replay_keeps_all_prior_defaults_and_drink_flag_off(monkeypatch):
    additions=(active.FLAG,"HIRO_ACTIVE_CARD_EFFECT_CONTEXT","HIRO_PLAN_EFFECT_REVALIDATION","HIRO_FALLBACK_EFFECT_SCORING")
    for key in additions:monkeypatch.setenv(key,"1")
    saved={key:False for key in replay.FLAGS if key not in additions}
    before=copy.deepcopy(saved)
    with replay._flags(saved):assert all(os.environ[key]=="0" for key in additions)
    assert before==saved and all(os.environ[key]=="1" for key in additions)
    assert "src/hiro/brain/active_drink_context.py" in replay.VERSION_FILES
