from types import SimpleNamespace as NS

import pytest

from hiro.brain.deciders import ProduceDeciders
from hiro.brain.review_card_roles import card_roles
from hiro.contracts import GameState
from hiro.state import context


def row(text, rarity="R"):
    return {"produceDescriptions": [{"text": text}], "effectGroupIds": ["effect_group-visible-exam_review-000"],
            "planType": "ProducePlanType_Plan2", "rarity": "ProduceCardRarity_" + rarity}


@pytest.fixture
def setup(monkeypatch):
    from hiro.brain import route_policy
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_REVIEW_FIRST_EXAM_ROLES", "1")
    idol = {"examEffectType": "ProduceExamEffectType_ExamReview", "planType": "ProducePlanType_Plan2"}
    # Exact uncustomized catalog text: hand-clap, charm, and resource-conditioned cashout.
    cards = {
        "cash": row("好印象の150%分パラメータ上昇レッスン中1回"),
        "builder": row("好印象+3以降、メンタルスキルカード使用時、好印象+1重複不可 レッスン中1回", "Sr"),
        "conditional": row("やる気消費3好印象の90%分パラメータ上昇スキルカード使用数追加+1重複不可"),
    }
    cat = NS(one=lambda *a: idol, card=lambda cid, upgrade: cards[cid])
    monkeypatch.setattr(context, "catalog", lambda: cat)
    monkeypatch.setattr(route_policy, "catalog", lambda: cat)
    decider = ProduceDeciders(None, idol_card_id="i_card-kllj-3-000")
    return decider, cards


def state(*, deck="builder", step=5, complete=True, candidate="cash"):
    cards = [] if deck is None else [{"card_id": deck, "upgrade": 0}]
    return GameState(produce={"mode": "produce-007", "step": step, "deck": cards,
                              "deck_size": len(cards) if complete else 8},
                     field_status={"produce.deck": "verified"} if complete else {},
                     page_fields={"candidates": [{"card_id": "builder", "upgrade": 0},
                                                 {"card_id": candidate, "upgrade": 0}]})


def pick(decider, current):
    result = decider.decide("SELECT_CARD", current)
    return result.action.args.get("pick_indexes"), result.reason


def test_actual_selection_path_fills_confirmed_cashout_gap_before_rarity(setup):
    decider, _ = setup
    chosen, why = pick(decider, state())
    assert chosen == [1] and "完整已核对" in why and "优先补一张" in why


def test_existing_cashout_does_not_demand_another(setup):
    decider, _ = setup
    chosen, why = pick(decider, state(deck="cash"))
    assert chosen == [0] and "首考前" not in why


def test_completely_unknown_deck_is_not_treated_as_missing_cashout(setup):
    decider, _ = setup
    chosen, why = pick(decider, state(deck=None, complete=False))
    assert chosen == [0] and "缺" not in why and "首考前" not in why


def test_partial_deck_uses_honest_soft_preference_not_absence_claim(setup):
    decider, _ = setup
    current = state(complete=False)
    # Keep both candidates unowned so only the soft role-vs-rarity choice differs.
    current.produce["deck"] = [{"card_id": "conditional", "upgrade": 0}]
    chosen, why = pick(decider, current)
    assert chosen == [1] and "全牌组未确认" in why and "不认定缺失" in why


@pytest.mark.parametrize("step", [None, 7, 8])
def test_unknown_day_or_after_first_exam_retains_neutral_sorting(setup, step):
    decider, _ = setup
    chosen, why = pick(decider, state(step=step))
    assert chosen == [1]  # unowned cash card still wins neutral novelty sorting
    assert "首考前" not in why


def test_conditional_cashout_is_not_claimed_as_unconditional(setup):
    decider, cards = setup
    roles = card_roles(cards["conditional"])
    assert roles.conditional and roles.extra_action and not roles.immediate_cashout
    current = state(candidate="conditional")
    current.produce["deck"] = [{"card_id": "conditional", "upgrade": 0}]
    chosen, why = pick(decider, current)
    assert chosen == [0] and "优先补一张" not in why


@pytest.mark.parametrize("text", [
    "好印象が10以上の場合、使用可好印象の400%分パラメータ上昇",
    "2ターン後、好印象の200%分パラメータ上昇",
    "以降、ターン開始時、好印象の100%分パラメータ上昇",
    "ターン終了時、好印象の100%分パラメータ上昇",
    "以降、好印象の100%分パラメータ上昇",
])
def test_conditions_and_delayed_triggers_are_not_invented_into_immediate_cashout(text):
    assert not card_roles(row(text)).immediate_cashout
    assert card_roles(row("好印象の150%分パラメータ上昇"), customized=True) is None


def test_new_role_feature_defaults_off(setup, monkeypatch):
    decider, _ = setup
    monkeypatch.delenv("HIRO_REVIEW_FIRST_EXAM_ROLES", raising=False)
    current = state()
    current.produce["deck"] = [{"card_id": "conditional", "upgrade": 0}]
    chosen, why = pick(decider, current)
    assert chosen == [0] and "首考前" not in why


@pytest.mark.parametrize("owned_pct,candidate_text,engine,expected", [
    (130, "好印象の200%分パラメータ上昇レッスン中1回", False, 1),
    (200, "好印象の200%分パラメータ上昇レッスン中1回", False, 0),
    (130, "好印象が10以上の場合、使用可好印象の400%分パラメータ上昇レッスン中1回", False, 0),
    (130, "好印象の200%分パラメータ上昇レッスン中1回", True, 0),
])
def test_limited_cashout_upgrade_does_not_displace_engine_or_ignore_conditions(setup, owned_pct, candidate_text, engine, expected):
    decider, cards = setup
    cards["base"] = row(f"好印象の{owned_pct}%分パラメータ上昇レッスン中1回")
    cards["cash"] = row(candidate_text)
    if not engine:
        cards["builder"] = row("好印象+6レッスン中1回", "Sr")
    current = state(deck="base")
    chosen, why = pick(decider, current)
    assert chosen == [expected]
    assert ("兑现升级软偏好" in why) == (expected == 1)


def test_different_route_or_finals_does_not_enable_role_heuristic(setup):
    decider, _ = setup
    current = state()
    current.produce["mode"] = "produce-008"
    _, why = pick(decider, current)
    assert "首考前" not in why
