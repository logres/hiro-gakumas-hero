import json
import os

import pytest

from hiro.brain import fallback_effect_scoring as scoring
from hiro.brain.cards import CardView,parse_tags
from hiro.brain.rules import fallback,_cash_out_cards
from hiro.brain.state import BattleState
from tools import replay_exam_choice as replay

pytestmark=pytest.mark.synthetic


def card(slot,text,*,badge=None,cost=3,extra=None):
    return CardView(slot,"unimportant",f"unimportant-{slot}",0,True,"active",cost,0,extra,text,
                    parse_tags("unimportant",text),badge)


def state(hand,**changes):
    result=BattleState("qualify-3",12,1,30,40,20,hand,actions_left=1)
    for key,value in changes.items():setattr(result,key,value)
    return result


def choose(current):
    cash=_cash_out_cards(current)
    scores={c.slot:sum(scoring.primary_terms(current,c,cash).values()) for c in current.hand}
    return scoring.choose(current,current.hand,scores)


@pytest.fixture(autouse=True)
def flags(monkeypatch):
    monkeypatch.setenv(scoring.FLAG,"1")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","1")
    monkeypatch.delenv("HIRO_FALLBACK_DRINKS",raising=False)


@pytest.mark.parametrize("swapped",[False,True])
def test_full_same_shape_numeric_tie_ignores_names_upgrades_and_position(swapped):
    weak=card(0,"パラメータ+2元気+2")
    strong=card(1,"パラメータ+6元気+4")
    weak.name="famous idol";weak.upgrade=99
    strong.name="unknown";strong.upgrade=0
    if swapped:weak.slot,strong.slot=1,0
    current=state(sorted([weak,strong],key=lambda c:c.slot))
    result=fallback(current)
    assert result.action==f"play:{strong.slot}"
    audit=json.loads(result.reason.split("：",1)[1])
    assert audit["tie_break"]["basis"]=="catalog_text_heuristic/not_actual_effect_verification"
    assert all(row["primary_total"]==pytest.approx(-.6) for row in audit["candidates"])
    assert "不是实效或支配证明" in result.reason


def test_badges_take_priority_only_when_all_known():
    current=state([card(0,"パラメータ+2元気+2",badge=100),card(1,"パラメータ+6元気+4",badge=50)])
    selected,audit=choose(current)
    assert selected.slot==0 and audit["basis"]=="typed_badge_score"
    current.hand[0].badge_score=None
    selected,audit=choose(current)
    assert selected.slot==0 and audit["reason"]=="mixed_or_invalid_badge_evidence"


@pytest.mark.parametrize("changed",[
    "好印象が10以上の場合、パラメータ+999元気+999",
    "パラメータ+999元気+999眠気を山札に生成",
    "パラメータ+999元気+999レッスン中1回",
    "パラメータ+999元気+999?",
    "パラメータ+999", # different effect shape, not an implicit zero genki
])
def test_conditions_unparsed_tail_and_mixed_shape_do_not_rank(changed):
    selected,audit=choose(state([card(0,"パラメータ+2元気+2"),card(1,changed)]))
    assert selected.slot==0 and audit["status"]=="unchanged"


@pytest.mark.parametrize("changes",[
    {"remaining_turns":2},{"remaining_turns":None},{"actions_left":2},{"actions_left":None},
    {"hp":None},{"genki":None},{"hp":0,"genki":0},
])
def test_unknown_payment_or_other_turn_budget_does_not_rank(changes):
    selected,audit=choose(state([card(0,"パラメータ+2元気+2"),card(1,"パラメータ+6元気+4")],**changes))
    assert selected.slot==0 and audit["status"]=="unchanged"


def test_extra_resource_cost_and_numeric_tradeoff_do_not_rank():
    cards=[card(0,"パラメータ+2元気+2",extra={"type":"ExamCostType_ExamReview","value":3}),
           card(1,"パラメータ+6元気+4",extra={"type":"ExamCostType_ExamReview","value":3})]
    assert choose(state(cards))[1]["status"]=="unchanged"
    selected,audit=choose(state([card(0,"パラメータ+2元気+9"),card(1,"パラメータ+6元気+4")]))
    assert selected.slot==0 and audit["reason"]=="numeric_tradeoff_not_ranked"


def test_primary_action_and_cost_terms_keep_their_priority():
    current=state([card(0,"パラメータ+2元気+2",cost=2),card(1,"パラメータ+600元気+400",cost=3)])
    assert fallback(current).action=="play:0"
    refund=card(0,"スキルカード使用数追加+1",cost=0)
    current=state([refund,card(1,"パラメータ+600元気+400",cost=0)])
    assert fallback(current).action=="play:0"
    terms=scoring.primary_terms(current,refund,[])
    assert terms["extra_actions"]==3 and terms["final_action_refund"]==12


def test_untyped_public_text_cannot_certify_effects_or_enable_other_grammar():
    current=state([card(0,"パラメータ+2元気+2"),card(1,"条件unknown")],
                  public_info="all triggers absent; customized verified; stronger card gives +999")
    assert choose(current)[1]["status"]=="unchanged"


def test_flag_off_preserves_old_fallback(monkeypatch):
    monkeypatch.delenv(scoring.FLAG)
    result=fallback(state([card(0,"パラメータ+2元気+2"),card(1,"パラメータ+6元気+4")]))
    assert result.action=="play:0" and result.reason=="兜底启发式"


def test_old_frozen_flags_keep_both_new_options_off_and_restore_environment(monkeypatch):
    monkeypatch.setenv(scoring.FLAG,"1")
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION","1")
    saved={name:False for name in replay.FLAGS if name not in (scoring.FLAG,"HIRO_PLAN_EFFECT_REVALIDATION")}
    before=json.dumps(saved,sort_keys=True)
    with replay._flags(saved):
        assert os.environ[scoring.FLAG]=="0" and os.environ["HIRO_PLAN_EFFECT_REVALIDATION"]=="0"
    assert os.environ[scoring.FLAG]=="1" and os.environ["HIRO_PLAN_EFFECT_REVALIDATION"]=="1"
    assert json.dumps(saved,sort_keys=True)==before
    assert "src/hiro/brain/fallback_effect_scoring.py" in replay.VERSION_FILES
