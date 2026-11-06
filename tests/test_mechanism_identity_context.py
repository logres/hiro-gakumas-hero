"""Read-only master identity definitions and shared deck evidence, without a model."""
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from hiro.brain import mechanism_card_selection as cards, route_drink_selection as drinks
from hiro.contracts import GameState
from hiro.contracts.game_state import Source


@pytest.fixture
def setup(monkeypatch):
    idols = {key: {"id": key, "characterId": "same-person", "examEffectType": "ProduceExamEffectType_ExamReview",
                   "planType": "ProducePlanType_Plan2", "produceCardId": "signature-" + key,
                   "beforeProduceItemId": "before-" + key, "afterProduceItemId": "after-" + key}
             for key in ("one", "two")}
    definitions = {(table, key): row for key, row in idols.items() for table in ("IdolCard",)}
    for key in idols:
        for version in ("before", "after"):
            definitions[("ProduceItem", version + "-" + key)] = {
                "id": version + "-" + key, "name": version + key,
                "produceDescriptions": [{"text": version + " exact " + key}, {"text": " conditional activation"}]}
    definitions[("ProduceDrink", "drink")] = {"id": "drink", "name": "Draw", "produceDescriptions": [{"text": "Draw two"}]}
    versions = {(key, up): {"id": key, "upgradeCount": up, "name": key,
                           "produceDescriptions": [{"text": key + " effect " + str(up)}], "stamina": up + 1}
                for key in ("signature-one", "signature-two", "deck-card") for up in (0, 1)}
    master = NS(one=lambda table, key: definitions[(table, key)], card=lambda key, up: versions[(key, up)])
    monkeypatch.setattr(drinks, "catalog", lambda: master)
    state = GameState(seq=8, produce={"deck": [{"card_id": "deck-card", "upgrade": 1}], "deck_size": 1},
                      page_fields={"candidates": [{"drink_id": "drink"}], "held": [], "full": False},
                      sources={"produce.deck": Source("screen", 7)},
                      field_status={"produce.deck": "verified", "produce.deck_size": "verified"})
    return state, master, idols, definitions, versions


def test_same_route_and_character_keep_distinct_exact_signature_and_items(setup):
    state, master, idols, _, _ = setup
    a, b = (cards.build_context(replace(state, page_fields={}), idols[key], {}, master)
            for key in ("one", "two"))
    assert a["idol"]["characterId"] == b["idol"]["characterId"]
    assert a["idol"]["examEffectType"] == b["idol"]["examEffectType"]
    for context, identity in ((a, "one"), (b, "two")):
        mechanisms = context["identity_mechanisms"]
        signature = mechanisms["signature_card"]
        assert [v["master_effect_text"] for v in signature["versions"]] == ["signature-" + identity + " effect 0", "signature-" + identity + " effect 1"]
        assert signature["actual_upgrade_status"] == "unknown" and signature["ownership_status"] == "not_observed"
        items = mechanisms["catalog_identity_item_variants"]
        assert [v["identity_reference"] for v in items["variants"]] == ["beforeProduceItemId", "afterProduceItemId"]
        assert items["variants"][1]["effect_text"] == "after exact " + identity + " conditional activation"
        assert items["equipment_status"] == items["trigger_status"] == "unknown"
        assert items["remaining_charges"] is None


def test_unknown_ids_and_missing_upgrade_never_borrow_another_variant(setup):
    state, master, idols, definitions, versions = setup
    versions.pop(("signature-one", 1))
    definitions.pop(("ProduceItem", "after-one"))
    mechanism = cards.build_context(replace(state, page_fields={}), idols["one"], {}, master)["identity_mechanisms"]
    assert mechanism["signature_card"]["versions"][0]["master_effect_text"]
    assert mechanism["signature_card"]["versions"][1]["master_effect_text"] is None
    unknown = mechanism["catalog_identity_item_variants"]["variants"][1]
    assert unknown["item_id"] == "after-one" and unknown["effect_text"] is None and unknown["status"] == "unknown"
    blank = cards.identity_context({}, master)
    assert blank["signature_card"]["versions"] == []
    assert all(v["effect_text"] is None for v in blank["catalog_identity_item_variants"]["variants"])
    payload, error = drinks.build_context(state, "missing-idol", can_skip=True)
    assert payload is None and error


def test_drink_reuses_same_identity_definitions_and_verified_deck(setup):
    state, master, idols, _, _ = setup
    expected = cards.build_context(replace(state, page_fields={}), idols["one"], {}, master)
    actual, error = drinks.build_context(state, "one", can_skip=False)
    assert error is None
    assert actual["identity_mechanisms"] == expected["identity_mechanisms"]
    assert actual["deck"] == expected["deck"]
    assert actual["deck"]["absence_claim_allowed"] is True
    assert actual["deck"]["observed_cards"][0]["master_effect_text"] == "deck-card effect 1"
    assert actual["deck"]["source_seq"] == 7


@pytest.mark.parametrize("case", ["pending", "unverified", "inferred", "no_source", "size", "unknown_version", "unknown_id", "malformed", "missing", "customized"])
def test_drink_deck_unknowns_keep_evidence_boundaries(setup, case):
    state, _, _, _, _ = setup
    if case == "pending":
        state.pending_review.append("produce.deck")
    elif case == "unverified":
        state.field_status["produce.deck"] = "observed"
    elif case == "inferred":
        state.field_status["produce.deck"] = "unknown"
        state.sources["produce.deck"] = Source("infer", 8)
    elif case == "no_source":
        state.field_status["produce.deck"] = "unknown"
        state.sources.clear()
    elif case == "size":
        state.produce["deck_size"] = 2
    elif case == "unknown_version":
        state.produce["deck"][0]["upgrade"] = None
    elif case == "unknown_id":
        state.produce["deck"][0]["card_id"] = "unrecognized"
    elif case == "malformed":
        state.produce["deck"] = "not a deck list"
    elif case == "missing":
        state.produce.pop("deck")
    elif case == "customized":
        state.produce["deck"][0]["customized"] = True
    actual, error = drinks.build_context(state, "one", can_skip=True)
    assert error is None
    deck = actual["deck"]
    if case == "customized":
        assert deck["observed_cards"][0]["observed_customized"] is True
        assert deck["customization_effects_known"] is False
    else:
        assert deck["complete"] is False and deck["absence_claim_allowed"] is False
    if case in ("missing", "malformed"):
        assert deck["observed_cards"] is None



def test_verified_resumed_deck_keeps_existing_completeness_contract(setup):
    state, _, _, _, _ = setup
    state.sources["produce.deck"] = Source("infer", 8)
    actual, error = drinks.build_context(state, "one", can_skip=True)
    assert error is None
    assert actual["deck"]["complete"] is True
    assert actual["deck"]["source"] == "infer"
