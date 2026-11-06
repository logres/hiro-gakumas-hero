import copy
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest

from hiro.brain import mechanism_drink_replacement as replacement, route_guard
from hiro.contracts import Action, ActionKind, Decision, GameState
from hiro.produce import drink_swap, hif

pytestmark=pytest.mark.synthetic


def fields(page="SELECT_DRINK"):
    held=[{"index":i,"drink_id":f"held-{i}","center":[62+i*85,1213]} for i in range(4)]
    new=[{"index":i,"drink_id":f"new-{i}","center":[100,350+i*90]} for i in range(3)]
    return {"held":held,"full":True,"complete":True,
            **({"candidates":new} if page=="SELECT_DRINK" else {"incomings":new,"incoming":new[-1]})}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_MECHANISM_DRINK_REPLACEMENT","1")
    def one(table,key):
        if table=="IdolCard":
            return {"id":key,"examEffectType":"ProduceExamEffectType_ExamReview"}
        return {"name":key,"produceDescriptions":[{"text":f"effect {key}; cost and duration"}]}
    monkeypatch.setattr(replacement,"catalog",lambda:NS(one=one))
    monkeypatch.setattr(replacement,"card_context",lambda *args:{"identity_mechanisms":{"route":"generic"},"deck":{"status":"unknown"}})
    class Decider:
        llm=NS(name="mock",model="mock")
        response={"option_id":"1","reason":"compare whole holding"}
        calls=[]
        overflow_skip=None
        def _uses_yaruki_policy(self,state):return False
        def _ask(self,prompts,payload):
            self.calls.append(payload)
            return self.response,[{"adapter":"mock","model":"mock","reply":self.response}]
    state=GameState(produce={"idol_card_id":"generic-id","drink_capacity":4,"step":8},page_fields=fields())
    return Decider(),state


def test_all_incoming_and_exact_combination_in_payload(setup):
    decider,state=setup
    result=replacement.choose(decider,state,"generic-id",page="SELECT_DRINK",n_options=3)
    assert result.source=="llm" and result.action.kind is ActionKind.DISCARD_DRINK
    assert result.action.args["pick_index"]==0 and result.action.args["discard"]==[0]
    payload=decider.calls[0]
    assert len(payload["incoming"])==3 and len(payload["options"])==13
    assert all("effects" in item for item in payload["held"]+payload["incoming"])
    assert all(len(option["resulting_drinks"])==4 for option in payload["options"])
    assert len(result.llm)==1 and "tiers" not in json.dumps(payload)


def test_multi_incoming_and_duplicate_ids_keep_physical_indices(setup):
    decider,state=setup
    state.page_fields=fields("PDRINK_MAX")
    state.page_fields["held"][1]["drink_id"]="held-0"
    payload,error=replacement.build_context(state,"other-idol",page="PDRINK_MAX")
    assert not error and len(payload["options"])<=70
    assert any(len(option["action_args"]["discard"])==3 for option in payload["options"])
    assert any(option["action_args"]["discard"]==[1] for option in payload["options"])
    state.page_fields["held"][1]["visible"]=False
    payload,error=replacement.build_context(state,"other-idol",page="PDRINK_MAX")
    assert not error
    assert all(1 not in option["action_args"]["discard"] for option in payload["options"])


@pytest.mark.parametrize("change",[
    {"full":None},{"held":None},{"held":[]},{"candidates":[{"drink_id":None}]},
    {"held":[{"index":i,"drink_id":"x","center":[1,1]} for i in (0,1,1,3)]},
    {"held":[{"index":i,"drink_id":"x"} for i in range(4)]},
    {"candidates":[{"slot":2,"drink_id":"new-0"}]},
])
def test_unknown_or_inconsistent_evidence_waits_before_model(setup,change):
    decider,state=setup
    state.page_fields.update(change)
    assert replacement.choose(decider,state,"generic-id",page="SELECT_DRINK").action.kind is ActionKind.WAIT
    assert not decider.calls


def test_capacity_incomplete_list_and_unknown_effect_wait(setup,monkeypatch):
    decider,state=setup
    state.produce["drink_capacity"]=3
    assert replacement.choose(decider,state,"generic-id",page="SELECT_DRINK").action.kind is ActionKind.WAIT
    state.produce["drink_capacity"]=4
    state.page_fields=fields("PDRINK_MAX")
    state.page_fields["complete"]=False
    assert replacement.choose(decider,state,"generic-id",page="PDRINK_MAX").action.kind is ActionKind.WAIT
    state.page_fields["complete"]=True
    monkeypatch.setattr(replacement,"catalog",lambda:NS(one=lambda *a:{"examEffectType":"known","produceDescriptions":[]}))
    assert replacement.choose(decider,state,"generic-id",page="PDRINK_MAX").action.kind is ActionKind.WAIT


@pytest.mark.parametrize("reply",[None,{}, {"option_id":True,"reason":"bad"},{"option_id":"999","reason":"bad"},
    {"option_id":"1","reason":""},{"option_id":"1","reason":"x","discard":[0]}])
def test_bad_reply_does_not_silently_drop_or_skip(setup,reply):
    decider,state=setup
    decider.response=reply
    assert replacement.choose(decider,state,"generic-id",page="SELECT_DRINK").action.kind is ActionKind.WAIT
    assert len(decider.calls)==1


def test_no_model_and_skip_permission(setup):
    decider,state=setup
    decider.llm=None
    assert replacement.choose(decider,state,"generic-id",page="SELECT_DRINK").action.kind is ActionKind.WAIT
    assert not decider.calls
    payload,error=replacement.build_context(state,"generic-id",page="SELECT_DRINK",can_skip=False)
    assert not error and all(option["action_args"]["receive"] for option in payload["options"])


def test_dispatch_keep_confirmation_and_flag_off(setup,monkeypatch):
    decider,state=setup
    decider.response={"option_id":"0","reason":"keep current combination"}
    state.page_fields=fields("PDRINK_MAX")
    result=route_guard.guard(decider,"PDRINK_MAX",state)
    assert result.action.args["mechanism_replacement"] and decider.overflow_skip is True
    decider.response={"option_id":"1","reason":"replace"}
    route_guard.guard(decider,"PDRINK_MAX",state)
    assert decider.overflow_skip is False
    decider.response=None
    assert route_guard.guard(decider,"PDRINK_MAX",state).action.kind is ActionKind.WAIT
    assert decider.overflow_skip is False
    monkeypatch.delenv("HIRO_MECHANISM_DRINK_REPLACEMENT")
    assert route_guard.guard(decider,"PDRINK_MAX",state).action.args=={"discard":[],"receive":False}
    decider._uses_yaruki_policy=lambda st:True
    assert route_guard.guard(decider,"PDRINK_MAX",state) is None


def test_fresh_gate_rejects_changed_index_or_identity_not_confidence():
    expected=fields()
    fresh=copy.deepcopy(expected)
    fresh["held"][0]["confidence"]=.1
    assert replacement.same_drink_identities(expected,fresh,page="SELECT_DRINK")
    fresh["held"][0]["drink_id"]="other"
    assert not replacement.same_drink_identities(expected,fresh,page="SELECT_DRINK")
    fresh=copy.deepcopy(expected)
    fresh["held"][0]["center"]=[200,600]
    assert not replacement.same_drink_identities(expected,fresh,page="SELECT_DRINK")
    assert not replacement.same_drink_identities(expected,{},page="SELECT_DRINK")


def strategy(monkeypatch,pf,decision):
    st=hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    recorded=[]
    st.s=NS(state=GameState(produce={"drink_capacity":4},page_fields=pf),
            observe=lambda **kw:NS(fields=pf),record=lambda *a,**kw:recorded.append(kw))
    st.deciders=NS(_uses_yaruki_policy=lambda state:False,decide=lambda *a,**kw:decision)
    st._stop=lambda page,reason,**kw:(_ for _ in ()).throw(RuntimeError(reason))
    return st,recorded


def test_select_full_uses_all_candidates_and_does_not_preselect_or_repeat(setup,monkeypatch):
    decider,state=setup
    decision=replacement.choose(decider,state,"generic-id",page="SELECT_DRINK")
    st,records=strategy(monkeypatch,state.page_fields,decision)
    seen=[]
    st.deciders.decide=lambda page,current,**kw:(seen.append(len(current.page_fields["candidates"])),decision)[1]
    monkeypatch.setattr(hif,"ocr",NS(ocr=lambda:[NS(text="Pドリンク所持上限")]))
    from hiro.brain import drinks
    monkeypatch.setattr(drinks,"best_incoming",lambda *a:(_ for _ in ()).throw(AssertionError("legacy preselection")))
    swaps=[]
    def failed(*a,**kw):
        swaps.append(a)
        assert kw["verify_current"](None)
        return NS(ok=False,error="old drink discarded; receive failed")
    monkeypatch.setattr(drink_swap,"discard_then_receive",failed)
    with pytest.raises(RuntimeError,match="不重放"):
        st._drink_full_skip(NS(fetch_select_drink=lambda:NS(can_skip=True,drinks=[1,2,3])))
    assert seen==[3] and len(swaps)==1 and records[0]["execution"].ok is False


def test_overflow_partial_failure_stops_before_legacy_retry(setup,monkeypatch):
    decider,state=setup
    state.page_fields=fields("PDRINK_MAX")
    decision=replacement.choose(decider,state,"generic-id",page="PDRINK_MAX")
    st,records=strategy(monkeypatch,state.page_fields,decision)
    swaps=[]
    def fail(*a,**kw):
        swaps.append(a)
        assert kw["strict_selection"] and kw["verify_current"](None)
        return NS(ok=False,error="commit outcome uncertain")
    monkeypatch.setattr(drink_swap,"resolve_overflow",fail)
    with pytest.raises(RuntimeError,match="不自动重试"):
        st.on_pdrink_max(None)
    assert len(swaps)==1 and len(records)==1


def test_executors_reject_fresh_identity_before_any_tap():
    image=np.zeros((1280,720,3),dtype=np.uint8)
    taps=[]
    common=dict(shoot=lambda:image,click=lambda *a:taps.append(a),calib=False,verify_current=lambda image:False)
    assert not drink_swap.swap_receive(0,0,strict=True,**common).ok
    assert not drink_swap.resolve_overflow([0],strict_selection=True,**common).ok
    assert taps==[]


@pytest.mark.parametrize("mechanism,card_text,item_text,drink_text,stamina",[
    ("ExamReview","好印象+7","ターン終了時、好印象1.5倍","好印象+3",20),
    ("ExamCardPlayAggressive","やる気+5元気+8","元気が20以上の場合、追加使用数+1","やる気+3",12),
    ("ExamConcentration","集中+4","アクティブ使用時、集中+1","パラメータ上昇量増加30%",30),
])
def test_real_shared_context_across_distinct_mechanisms(setup,monkeypatch,mechanism,card_text,item_text,drink_text,stamina):
    decider,state=setup
    from hiro.brain.mechanism_card_selection import build_context
    def one(table,key):
        if table=="IdolCard":
            return {"id":key,"examEffectType":"ProduceExamEffectType_"+mechanism,
                    "produceCardId":"signature","beforeProduceItemId":"item"}
        return {"id":key,"name":key,"produceDescriptions":[{"text":item_text if table=="ProduceItem" else drink_text}]}
    master=NS(one=one,card=lambda cid,up:{"name":cid,"produceDescriptions":[{"text":card_text}],"stamina":up+1})
    monkeypatch.setattr(replacement,"catalog",lambda:master)
    monkeypatch.setattr(replacement,"card_context",build_context)
    state.produce.update(stamina=stamina,deck=[{"card_id":"owned","upgrade":1}],deck_size=1)
    state.field_status.update({"produce.deck":"verified","produce.deck_size":"verified"})
    result=replacement.choose(decider,state,"arbitrary-id",page="SELECT_DRINK")
    assert result.action.kind is ActionKind.DISCARD_DRINK
    payload=decider.calls[0]
    assert payload["identity_mechanisms"]["signature_card"]["versions"][1]["master_effect_text"]==card_text
    assert payload["identity_mechanisms"]["catalog_identity_item_variants"]["variants"][0]["effect_text"]==item_text
    assert payload["deck"]["complete"] and payload["deck"]["observed_cards"][0]["master_effect_text"]==card_text
    assert payload["held"][0]["effects"]==drink_text and payload["known_resources"]["stamina"]==stamina


def test_strict_overflow_never_fills_extra_unapproved_bottle(monkeypatch):
    image=np.zeros((1280,720,3),dtype=np.uint8)
    taps=[]
    monkeypatch.setattr(drink_swap,"find_text",lambda boxes,needles,**kw:(100,500) if needles==drink_swap.OVERFLOW_HEADER else (300,1100))
    monkeypatch.setattr(drink_swap,"checkboxes",lambda image:[(300,False),(400,False),(600,True),(700,True)])
    monkeypatch.setattr(drink_swap,"_toggle",lambda *args:None)
    monkeypatch.setattr(drink_swap,"select_left",lambda boxes:1)
    result=drink_swap.resolve_overflow([0],receive_indexes=[0],held=[{},{}],incomings=[{},{}],
        strict_selection=True,verify_current=lambda image:True,shoot=lambda:image,
        click=lambda *a:taps.append(a),ocr=lambda image:[],calib=False)
    assert not result.ok and "没有选满" in result.error and taps==[]


def test_wrong_detail_identity_never_presses_discard(monkeypatch):
    image=np.zeros((1280,720,3),dtype=np.uint8)
    from hiro.produce.ops import Run
    from hiro.vision import items
    monkeypatch.setattr(items,"_drink_effects",lambda:{"wanted":("Wanted","effect"),"other":("Other","different")})
    boxes=[("Pドリンク詳細",1,(100,400,300,430)),("Other",1,(150,500,300,530)),("捨てる",1,(560,870,650,900))]
    taps=[]
    monkeypatch.setattr(drink_swap,"slot_empty",lambda *a:False)
    monkeypatch.setattr(drink_swap,"occupied",lambda *a:4)
    run=Run(Action.activate_effect(0),"SELECT_DRINK",lambda:image,lambda *a:taps.append(a),lambda:0,lambda t:None,ocr=lambda image:boxes)
    error=drink_swap.discard_owned(run,0,[{"state":"drink","center":[62,1213],"drink_id":"wanted"}],strict=True)
    assert "不丢弃" in error and taps==[(62,1213)]


def test_exact_modal_name_is_required_and_unknown_or_wrapped_name_waits(monkeypatch):
    from hiro.vision import items
    monkeypatch.setattr(items,"_drink_effects",lambda:{"wanted":("Wanted","effect"),"other":("Other","effect")})
    title=("Pドリンク詳細",1,(100,400,300,430))
    button=("捨てる",1,(560,870,650,900))
    assert drink_swap._named_drink_identity([title,("Wanted",1,(150,500,300,530)),button],"wanted")
    assert not drink_swap._named_drink_identity([title,("Want",1,(150,500,300,530)),button],"wanted")


def test_button_color_change_is_not_strict_receive_success(monkeypatch):
    image=np.zeros((1280,720,3),dtype=np.uint8)
    taps=[]
    ticks=[0]
    def clock():
        ticks[0]+=1
        return ticks[0]
    monkeypatch.setattr(drink_swap,"discard_owned",lambda *a,**kw:None)
    monkeypatch.setattr(drink_swap,"button_sv",lambda *a:(200,200))
    monkeypatch.setattr(drink_swap,"orange_lit",lambda *a:True)
    monkeypatch.setattr(drink_swap,"_roi_changed",lambda *a:True)
    result=drink_swap.swap_receive(0,0,shoot=lambda:image,click=lambda *a:taps.append(a),clock=clock,sleep=lambda t:None,
        ocr=lambda image:[],calib=False,strict=True,verify_current=lambda image:True,
        verify_discarded=lambda image:True,verify_received=lambda image:False)
    assert not result.ok and "旧饮料已丢弃" in result.error
    assert taps.count(drink_swap.RECEIVE_TAP)==1


def test_keep_commit_without_effect_is_not_success_or_skip_authorization(setup,monkeypatch):
    decider,state=setup
    decider.response={"option_id":"0","reason":"keep"}
    decision=replacement.choose(decider,state,"generic-id",page="SELECT_DRINK")
    st,records=strategy(monkeypatch,state.page_fields,decision)
    st._skip_incoming_drink=True  # A prior permission must not survive this attempt.
    commits=[]
    monkeypatch.setattr(hif,"device",NS(screenshot=lambda:None))
    monkeypatch.setattr(drink_swap,"wait_skip_result",lambda action:NS(ok=False,error="no confirmation"))
    ctx=NS(fetch_select_drink=lambda:NS(can_skip=True,drinks=[1,2,3]),commit=lambda *a:commits.append(a))
    with pytest.raises(RuntimeError,match="不重放"):
        st._mechanism_drink_full(ctx,NS())
    assert len(commits)==1 and not st._skip_incoming_drink and records[0]["execution"].ok is False


def test_skip_result_requires_expected_confirmation_without_clicking():
    ticks=[0]
    def clock():
        ticks[0]+=1
        return ticks[0]
    action=Action(ActionKind.DISCARD_DRINK,{"receive":False,"discard":[]})
    assert not drink_swap.wait_skip_result(action,shoot=lambda:None,ocr=lambda image:[],clock=clock,sleep=lambda t:None,timeout=2).ok
    result=drink_swap.wait_skip_result(action,shoot=lambda:None,
        ocr=lambda image:[("報酬スキップ",1,(100,400,400,430))],clock=clock,sleep=lambda t:None,timeout=2)
    assert result.ok and result.page_after=="PDRINK_MAX_CONFIRM"
