import json
import os
from types import SimpleNamespace

import pytest

from hiro.brain import plan_evidence as evidence
from hiro.brain.battle import BattleBrain
from hiro.brain.cards import CardView
from hiro.brain.llm import MockLLM
from hiro.brain.state import BattleState, ExamMemory
from hiro.contracts import Action
from hiro.contracts.trace import freeze_exam_decision_input
from tools import replay_exam_choice as replay

pytestmark = pytest.mark.synthetic


def state(text="+7", *, slot=0, equipment=None, detail=True, framehash="a"):
    cards = [{"card_id": "generic-a", "upgrade": 1, "slot": slot, "snapshot_sha256": framehash*64,
              "raw_ocr_lines": [text], "actual_effects_status": "unknown",
              "vision_transcription": {"status": "model_transcription_unverified", "lines": [text],
                                       "uncertain_spans": [], "provenance": {"hash": framehash}}}]
    info = "已验证主数据与本帧装备识别：" + json.dumps({"observed_pitems": equipment or []})
    if detail:
        info += "\n本帧卡牌详情原始证据：" + json.dumps({"cards": cards})
    return BattleState(exam="qualify-1", turn=1, remaining_turns=5, hp=30, max_hp=40, genki=10,
        actions_left=1, hand=[CardView(slot,"A","generic-a",1,True,"mental",0,0,None,"好印象+1"),
                             CardView(1 if slot != 1 else 2,"B","generic-b",0,True,"mental",0,0,None,"好印象+2")],
        public_info=info)


def memory(plan=None):
    return ExamMemory(exam="qualify-1", turn=1, plan=plan or [{"action": "play", "card": "A"}],
                      expected_hand=["A", "B"])


def test_new_effect_replans_once_and_strips_metadata_from_model_hint(monkeypatch):
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION", "1")
    llm = MockLLM([{"action": "play:1", "reason": "new evidence", "plan": [{"action": "play", "card": "A"}]}])
    brain, current, mem = BattleBrain(None, llm), state(), memory()
    decision = brain.decide(current, mem)
    assert decision.source == "llm" and len(llm.calls) == 1
    assert "旧计划仅供重新评估" in llm.calls[0][1] and evidence.KEY not in llm.calls[0][1]
    assert evidence.KEY not in json.dumps(decision.plan)
    assert evidence.KEY in mem.plan[0]
    assert brain.decide(state(framehash="b"), mem).source == "plan"
    assert len(llm.calls) == 1


def test_slots_hashes_removed_cards_and_missing_observation_do_not_invalidate():
    old = state()
    plan = evidence.stamp([{"action": "play", "card": "A"}], old)
    assert not evidence.changed(plan, state(slot=3, framehash="b"))
    current = state()
    current.hand = current.hand[1:]
    assert not evidence.changed(plan, current)
    assert not evidence.changed(plan, state(detail=False))
    assert evidence.changed(plan, state("condition: impression >=10; +4"))


def test_equipment_variant_effect_and_charges_change_but_not_geometry():
    item = {"variant_status": "unknown", "observed_asset": "icon", "rect": [0,0,2,2],
            "remaining_charges": 1, "candidate_variants": [{"item_id": "p", "effect_text": "multiply"}]}
    plan = evidence.stamp([{"action": "play", "card": "A"}], state(equipment=[item]))
    assert not evidence.changed(plan, state(equipment=[{**item, "rect": [1,2,3,4], "hash": "different"}]))
    assert evidence.changed(plan, state(equipment=[{**item, "remaining_charges": 0}]))
    unknown_plan = evidence.stamp([{"action": "play", "card": "A"}], state(equipment=[{**item,"remaining_charges":None}]))
    assert evidence.changed(unknown_plan,state(equipment=[item]))
    assert evidence.changed(plan, state(equipment=[{**item, "variant_status": "confirmed_id", "item_id": "p"}]))
    assert evidence.changed(plan, state(equipment=[{**item, "candidate_variants": [{"item_id": "p", "effect_text": "different"}]}]))


def test_flag_off_preserves_plan_and_no_model_revalidation_uses_fallback(monkeypatch):
    monkeypatch.delenv("HIRO_PLAN_EFFECT_REVALIDATION", raising=False)
    llm = MockLLM([])
    assert BattleBrain(None,llm).decide(state(),memory()).source == "plan"
    assert not llm.calls
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION", "1")
    mem = memory()
    decision = BattleBrain(None,None).decide(state(),mem)
    assert decision.source != "plan"
    assert evidence.KEY not in json.dumps(decision.plan)


def test_metadata_survives_slicing_json_and_complete_frozen_replay(monkeypatch):
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION", "1")
    current = state()
    plan = evidence.stamp([{"action": "play", "card": "A"}, {"action": "play", "card": "B"}], current)
    mem = memory(json.loads(json.dumps(plan))[1:])
    assert not evidence.changed(mem.plan,current)
    brain = BattleBrain(None, MockLLM([]))
    advisor = SimpleNamespace(profile=None)
    frozen = freeze_exam_decision_input(current,mem,[Action.from_legal(a) for a in current.legal_actions()],[],
        advisor=advisor,source=SimpleNamespace(confidence=lambda:"screen"),idol_card_id=None)
    saved, replaymem, *_ = replay._state(json.loads(json.dumps(frozen["input"])))
    assert frozen["input"]["flags"]["HIRO_PLAN_EFFECT_REVALIDATION"] is True
    assert brain.decide(saved,replaymem).source == "plan"
    assert mem.plan == plan[1:]


def test_legacy_flags_disable_new_option_without_mutating_input(monkeypatch):
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION", "1")
    old = {key: False for key in replay.FLAGS if key != "HIRO_PLAN_EFFECT_REVALIDATION"}
    original = json.dumps(old,sort_keys=True)
    with replay._flags(old):
        assert os.environ["HIRO_PLAN_EFFECT_REVALIDATION"] == "0"
    assert os.environ["HIRO_PLAN_EFFECT_REVALIDATION"] == "1"
    assert json.dumps(old,sort_keys=True) == original
    for invalid in ({**old,"UNKNOWN":False}, {key:value for key,value in old.items() if key != "HIRO_FINAL_TURN_SETUP"}):
        with pytest.raises(ValueError):
            with replay._flags(invalid):
                pass


def test_committed_plan_slices_private_basis_without_exposing_it(monkeypatch):
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION", "1")
    current, mem = state(), memory()
    mem.plan = evidence.stamp([{"action":"play","card":"A"},{"action":"play","card":"B"}], current)
    brain = BattleBrain(None,MockLLM([]))
    decision = brain.decide(current,mem)
    assert evidence.KEY not in json.dumps(decision.plan)
    brain.commit(current,mem,decision)
    assert len(mem.plan) == 1 and evidence.KEY in mem.plan[0]
    assert mem.expected_hand == ["B"]



def test_verified_exam_groups_replan_on_new_draw_facts_not_frame_or_hand_removal():
    def observed(*,cards=("a","a"),framehash="a",verified=True,hand_count=3):
        current=state()
        current.public_info += "\n本帧考试分组快照："+json.dumps({"scope":"current_exam_groups",
            "restoration_verified":verified,"snapshot_sha256":framehash,
            "groups":[{"pile":"hand","count":hand_count,"complete":False},
                      {"pile":"draw","count":len(cards),"complete":True,
                       "cards":[{"card_id":c,"observed_thumbnail_upgrade":0,"rect":[1,2,3,4]} for c in cards]}]})
        return current
    old=evidence.stamp([{"action":"play","card":"A"}],state())
    assert evidence.changed(old,observed())
    plan=evidence.stamp([{"action":"play","card":"A"}],observed())
    assert not evidence.changed(plan,observed(framehash="new",hand_count=2))
    assert evidence.changed(plan,observed(cards=("a",)))
    assert evidence.changed(plan,observed(cards=("a","b")))
    assert not evidence.changed(old,observed(verified=False))
    assert not evidence.changed(plan,state())  # Missing observation is not an empty draw pile.
