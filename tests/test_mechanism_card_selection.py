import json
from types import SimpleNamespace as NS

import pytest

from hiro.brain import route_policy
from hiro.brain.deciders import ProduceDeciders
from hiro.brain.hif_rules import effect_group
from hiro.brain.llm import LLMResult
from hiro.contracts import GameState
from hiro.state import context


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_CARD_SELECTION", "1")
    idols = {}
    cards = {}

    def one(table, key):
        return idols[key]

    def card(key, upgrade):
        return cards[(key, upgrade)]

    cat = NS(one=one, card=card)
    monkeypatch.setattr(context, "catalog", lambda: cat)
    monkeypatch.setattr(route_policy, "catalog", lambda: cat)

    class Model:
        name, model = "mock", "synthetic"
        response = {"action": "pick", "index": 1, "reason": "Compare setup and cashout conditions, not rarity."}

        def __init__(self):
            self.calls = []

        def ask_json(self, system, user):
            self.calls.append((system, json.loads(user)))
            return LLMResult(self.response, json.dumps(self.response), .02, None, self.name, self.model)

    def scenario(identity="variant-a", effect="ExamReview", plan="Plan2"):
        idols[identity] = {"id": identity, "name": identity, "characterId": "same-character", "produceCardId": "signature-" + identity,
                           "examEffectType": "ProduceExamEffectType_" + effect, "planType": "ProducePlanType_" + plan}
        for cid, rarity, text in [("a", "Ssr", "好印象+6レッスン中1回"),
                                  ("b", "R", "好印象の200%分パラメータ上昇レッスン中1回")]:
            cards[(cid, 0)] = {"name": cid, "rarity": "ProduceCardRarity_" + rarity,
                              "effectGroupIds": [effect_group(idols[identity]["examEffectType"])],
                              "planType": idols[identity]["planType"], "produceDescriptions": [{"text": text}], "stamina": 2}
        model = Model()
        decider = ProduceDeciders(None, model, idol_card_id=identity)
        current = GameState(produce={"idol_card_id": identity, "mode": "produce-007", "step": 5},
                            page_fields={"candidates": [{"card_id": "a", "upgrade": 0}, {"card_id": "b", "upgrade": 0},
                                                         {"card_id": "unknown", "upgrade": 0}]})
        return decider, model, current
    return scenario, idols, cards


@pytest.mark.parametrize("effect,plan", [("ExamReview", "Plan2"), ("ExamCardPlayAggressive", "Plan2"), ("ExamParameterBuff", "Plan1")])
def test_regular_pick_uses_neutral_mechanism_context_for_each_master_route(setup, monkeypatch, effect, plan):
    scenario, _, _ = setup
    decider, model, current = scenario(effect=effect, plan=plan)
    monkeypatch.setattr(decider, "_fish_for_musts", lambda *a: pytest.fail("Opt-in ordinary selection must bypass specialist musts"))
    result = decider.decide("SELECT_CARD", current, n_options=3)
    assert result.source == "llm" and result.action.args["pick_indexes"] == [1] and len(result.llm) == 1
    payload = model.calls[0][1]
    assert payload["idol"]["examEffectType"] == "ProduceExamEffectType_" + effect
    assert payload["idol"]["planType"] == "ProducePlanType_" + plan
    assert [c["index"] for c in payload["candidates"]] == [0, 1]
    assert all(c["master_effect_text"] for c in payload["candidates"])
    assert "社区评级" not in str(payload) and "YARUKI" not in str(payload)


def test_same_character_different_card_versions_keep_exact_master_identity(setup):
    scenario, _, _ = setup
    first, model_a, state_a = scenario("variant-a", "ExamReview", "Plan2")
    first.decide("SELECT_CARD", state_a)
    second, model_b, state_b = scenario("variant-b", "ExamCardPlayAggressive", "Plan2")
    second.decide("SELECT_CARD", state_b)
    a, b = model_a.calls[0][1]["idol"], model_b.calls[0][1]["idol"]
    assert a["characterId"] == b["characterId"]
    assert a["id"] != b["id"] and a["examEffectType"] != b["examEffectType"] and a["produceCardId"] != b["produceCardId"]


def test_partial_deck_versions_customization_and_cost_unknowns_are_explicit(setup):
    scenario, _, _ = setup
    decider, model, current = scenario()
    current.produce.update(deck=[{"card_id": "a", "upgrade": None}, {"card_id": "b", "upgrade": 0, "customized": True}], deck_size=8)
    current.field_status["produce.deck"] = "verified"
    decider.decide("SELECT_CARD", current)
    payload = model.calls[0][1]
    assert payload["deck"]["complete"] is False and payload["deck"]["absence_claim_allowed"] is False
    assert payload["deck"]["versions_known"] is False
    assert payload["deck"]["observed_cards"][0]["master_effect_text"] is None
    assert payload["deck"]["observed_cards"][1]["observed_customized"] is True
    assert payload["deck"]["customization_effects_known"] is False
    assert payload["candidates"][0]["costs"]["forceStamina"] is None


def test_list_alone_is_not_complete_deck_evidence(setup):
    scenario, _, _ = setup
    decider, model, current = scenario()
    current.produce.update(deck=[{"card_id": "a", "upgrade": 0}], deck_size=1)
    decider.decide("SELECT_CARD", current)
    assert model.calls[0][1]["deck"]["complete"] is False


@pytest.mark.parametrize("status,pending", [("pending", []), ("unknown", []), ("verified", ["produce.deck"])])
def test_screen_source_and_equal_count_do_not_override_pending_or_unknown(setup, status, pending):
    from hiro.contracts.game_state import Source
    scenario, _, _ = setup
    decider, model, current = scenario()
    current.produce.update(deck=[{"card_id": "a", "upgrade": 0}], deck_size=1)
    current.sources["produce.deck"] = Source("screen", 1)
    current.field_status["produce.deck"] = status
    current.pending_review = pending
    decider.decide("SELECT_CARD", current)
    deck = model.calls[0][1]["deck"]
    assert deck["complete"] is False and deck["absence_claim_allowed"] is False


@pytest.mark.parametrize("response", [None, {"action": "pick", "index": 2, "reason": "unknown"},
    {"action": "pick", "index": True, "reason": "boolean"}, {"action": "pick", "index": "1", "reason": "string"},
    {"action": "reroll", "reason": "not supported"}, {"action": "pick", "index": 1}])
def test_failed_or_invalid_model_retains_explicit_neutral_rule_with_trace(setup, response):
    scenario, _, _ = setup
    decider, model, current = scenario()
    model.response = response
    result = decider.decide("SELECT_CARD", current)
    assert result.source == "rule" and result.action.args["pick_indexes"] == [0]
    assert "保留既有规则" in result.reason and len(result.llm) == 1 and len(model.calls) == 1


def test_default_off_and_change_pick_do_not_call_mechanism_model(setup, monkeypatch):
    scenario, _, _ = setup
    decider, model, current = scenario()
    monkeypatch.delenv("HIRO_MECHANISM_CARD_SELECTION", raising=False)
    assert decider.select_card(current).action.args["pick_indexes"] == [0]
    assert model.calls == []
    monkeypatch.setenv("HIRO_MECHANISM_CARD_SELECTION", "1")
    assert decider.select_card(current, change=True).action.args["pick_indexes"] == [0]
    assert model.calls == []
