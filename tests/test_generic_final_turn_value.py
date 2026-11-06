"""Mechanism counterexamples for generic final-turn coercion, without a model.

Cards are synthetic, using the real CardView/tag parser and observed score
badges. No claim is made that these exact combinations occur on a named card.
At multiplier 1000 and without buffs/items, final-turn impression settlement
is its remaining stack count (the mechanism documented in exam_generic.md).
"""

import pytest

from hiro.brain.cards import CardView, parse_tags
from hiro.brain.rules import Decision, final_turn_override, final_turn_plan, violations
from hiro.brain.state import BattleState, ExamMemory


def card(slot, text, badge=None, extra_cost=None):
    return CardView(slot, f"mechanism-{slot}", f"synthetic-{slot}", 0, True,
                    "active", 0, 0, extra_cost, text,
                    parse_tags(f"mechanism-{slot}", text), badge)


def state(hand, *, effect="ExamReview", impression=20, genki=0, actions=1):
    return BattleState("qualify-1", 10, 1, 30, 45, genki, hand,
                       impression=impression, actions_left=actions,
                       multiplier_permil=1000,
                       recommended_effect="ProduceExamEffectType_" + effect)


@pytest.fixture(autouse=True)
def explicit_generic(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_FINAL_TURN_SETUP", "1")


def test_impression_cost_cashout_must_not_override_better_natural_settlement():
    cash = card(0, "好印象消費10好印象の50%分パラメータ上昇", 5,
                {"type": "ExamCostType_ExamReview", "value": 10})
    current = state([cash])
    assert cash.tags.impression_score_pct == 50
    assert "play:0" in current.legal_actions()
    # The badge is the observed immediate score, after the resource payment.
    # Cash gives 5 now + 10 at turn end, versus skip retaining all 20 stacks.
    play_total = cash.badge_score + current.impression - cash.extra_cost["value"]
    assert play_total == 15 < current.impression == 20
    assert final_turn_override(current, Decision("skip", "retain settlement", "llm")) is None


def test_cost_free_impression_cashout_can_add_to_natural_settlement():
    cash = card(0, "好印象の50%分パラメータ上昇", 10)
    current = state([cash])
    assert cash.badge_score + current.impression == 30 > 20
    forced = final_turn_override(current, Decision("skip", "skip", "llm"))
    assert forced is not None and forced.action == "play:0"


def test_two_actions_allow_setup_before_impression_cashout():
    cash = card(0, "好印象の100%分パラメータ上昇", 20)
    setup = card(1, "好印象+5")
    current = state([cash, setup], actions=2)
    # Setup -> cash -> settlement = 25 + 25; cash -> setup -> settlement
    # = 20 + 25. With two actions, the observed cash-only plan is incomplete.
    assert (20 + 5) * 2 == 50 > 20 + 25 == 45
    choice = Decision("play:1", "setup then cash", "llm",
                      plan=[{"action": "play", "card": cash.name}])
    assert choice.action in current.legal_actions()
    assert final_turn_override(current, choice) is None
    assert choice.plan == [{"action": "play", "card": cash.name}]


@pytest.mark.parametrize("effect", ["ExamConcentration", "ExamLessonBuff"])
def test_concentration_and_good_condition_without_cashout_are_not_coerced(effect):
    direct = card(0, "パラメータ+100", 100)
    current = state([direct], effect=effect, impression=None)
    assert not direct.tags.genki_score_pct and not direct.tags.impression_score_pct
    assert final_turn_plan(current) is None
    assert final_turn_override(current, Decision("play:0", "observed 100", "llm")) is None


@pytest.mark.parametrize("effect", ["ExamConcentration", "ExamLessonBuff"])
def test_other_route_direct_badge_must_not_lose_to_incidental_genki_cashout(effect):
    cash = card(0, "元気の100%分パラメータ上昇", 1)
    direct = card(1, "パラメータ+100", 100)
    current = state([cash, direct], effect=effect, impression=None, genki=1)
    assert current.actions_left == 1
    assert direct.badge_score == 100 > cash.badge_score == 1
    assert "play:1" in current.legal_actions()
    # Both badges already contain the current route's modifiers. No formula
    # for concentration/good condition is needed to prove this ordering.
    assert final_turn_override(current, Decision("play:1", "observed 100", "llm")) is None
    assert violations(current, Decision("play:1", "observed 100", "llm")) == []


@pytest.mark.parametrize("cost", [
    {"type": "ExamCostType_ExamReview"},
    {"type": "ExamCostType_ExamReview", "value": None},
    {"type": "ExamCostType_ExamReview", "value": -1},
    {"type": "ExamCostType_ExamReview", "value": "10"},
    {"value": 10},
])
def test_unknown_cost_does_not_prove_cash_plan_superior(cost):
    cash = card(0, "好印象の50%分パラメータ上昇", 10, cost)
    setup = card(1, "好印象+20")
    current = state([cash, setup])
    choice = Decision("play:1", "settlement setup", "llm")
    assert final_turn_plan(current) is None
    assert final_turn_override(current, choice) is None
    assert violations(current, choice) == []


def test_unknown_cash_badge_does_not_displace_known_direct_output():
    cash = card(0, "元気の100%分パラメータ上昇")
    direct = card(1, "パラメータ+100", 100)
    current = state([cash, direct], genki=1)
    assert current.cash_formula(cash) == 1  # incomplete estimate, not a badge
    choice = Decision("play:1", "observed output", "llm")
    assert final_turn_override(current, choice) is None
    assert violations(current, choice) == []


def test_unknown_direct_badge_is_not_invented_as_a_higher_score():
    cash = card(0, "元気の100%分パラメータ上昇", 10)
    direct = card(1, "パラメータ+100")
    current = state([cash, direct], genki=10)
    choice = Decision("play:1", "unknown direct badge", "llm")
    assert final_turn_override(current, choice).action == "play:0"
    assert violations(current, choice)


@pytest.mark.parametrize("case", ["cost", "direct", "setup"])
def test_generic_choices_survive_guard_and_advisor(case):
    from hiro.brain.llm import MockLLM
    from hiro.contracts import Action
    from hiro.defaults.advisor import RuleLLMAdvisor
    from hiro.produce.exam_policy import guard_llm

    if case == "cost":
        current = state([card(0, "好印象消費10好印象の50%分パラメータ上昇", 5,
                              {"type": "ExamCostType_ExamReview", "value": 10})])
        action = "skip"
    elif case == "direct":
        current = state([card(0, "元気の100%分パラメータ上昇", 1),
                         card(1, "パラメータ+100", 100)],
                        effect="ExamConcentration", genki=1, impression=None)
        action = "play:1"
    else:
        current = state([card(0, "好印象の100%分パラメータ上昇", 20),
                         card(1, "好印象+5")], actions=2)
        action = "play:1"
    llm = MockLLM([{"action": action, "reason": "observed mechanisms"}])
    advisor = RuleLLMAdvisor(None, llm)
    memory = ExamMemory("qualify-1")
    choice = Decision(action, "observed mechanisms", "llm")
    assert guard_llm(current, memory, advisor.brain, choice) is choice
    legal = [Action.from_legal(a) for a in current.legal_actions()]
    result = advisor.decide(current, memory, None, legal)
    assert result.action.legal_key() == action
    assert len(llm.calls) == 1


def test_legacy_default_retains_existing_coercion(monkeypatch):
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    cash = card(0, "元気の100%分パラメータ上昇", 1)
    direct = card(1, "パラメータ+100", 100)
    current = state([cash, direct], effect="ExamConcentration", impression=None, genki=1)
    choice = Decision("play:1", "observed output", "llm")
    assert final_turn_override(current, choice).action == "play:0"
    assert violations(current, choice)
