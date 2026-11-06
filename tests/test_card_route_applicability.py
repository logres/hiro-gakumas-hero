from types import SimpleNamespace as NS

import pytest

from hiro.brain.deciders import ProduceDeciders
from hiro.contracts import ActionKind, GameState
from hiro.state import context


@pytest.fixture
def route(monkeypatch):
    from hiro.brain import route_policy
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    idol = {"examEffectType": "ProduceExamEffectType_ExamReview"}
    monkeypatch.setattr(route_policy, "recommended_effect", lambda identity: idol["examEffectType"].split("_", 1)[-1])
    cards = {
        "yaruki-must": {"effectGroupIds": ["effect_group-visible-exam_card_play_aggressive-000"]},
        "review-b": {"effectGroupIds": ["effect_group-visible-exam_review-000"]},
        "review-a": {"effectGroupIds": ["effect_group-visible-exam_review-000"]},
    }
    def card(cid, upgrade):
        return cards[cid]
    monkeypatch.setattr(context, "catalog", lambda: NS(one=lambda *a: idol, card=card))
    monkeypatch.setattr(context, "preview_card_pick", lambda *a, **k: pytest.fail("Must not use yaruki previews"))
    decider = ProduceDeciders(None, idol_card_id="i_card-skin-kllj-3-000")
    monkeypatch.setattr(decider, "_fish_for_musts", lambda *a: pytest.fail("Must not spend on yaruki musts"))
    return decider, idol


def state(*ids, deck=None, recommended=None):
    return GameState(produce={"deck": deck or []}, page_fields={
        "candidates": [{"card_id": cid, "upgrade": upgrade} for cid, upgrade in ids],
        "rerolls_left": 4, "excludes_left": 2, "recommended": recommended})


def test_review_picks_catalog_recommended_over_yaruki_must_without_spending(route):
    decider, _ = route
    result = decider.select_card(state(("yaruki-must", 1), ("review-b", 1)))
    assert result.action.kind is ActionKind.ACTIVATE_EFFECT
    assert result.action.args["pick_indexes"] == [1]
    assert decider.picked_musts == set() and decider._page_spend == {}
    assert all("社区评级" not in (c.preview or {}) for c in result.candidates)


@pytest.mark.parametrize("owned,expected", [
    ([{"card_id": "review-b", "upgrade": 1}], [1]),
    ([{"card_id": "review-b", "upgrade": 0}], [0]),
])
def test_prefer_nonduplicate_or_better_upgrade(route, owned, expected):
    decider, _ = route
    raw = state(("review-b", 1), ("review-a", 0), deck=owned)
    if owned[0]["upgrade"] == 0:
        raw.page_fields["candidates"] = raw.page_fields["candidates"][:1]
    assert decider.select_card(raw).action.args["pick_indexes"] == expected


def test_equal_metadata_tie_uses_card_identity_not_slot(route):
    decider, _ = route
    result = decider.select_card(state(("review-b", 1), ("review-a", 1)))
    assert result.action.args["pick_indexes"] == [1]
    assert "依据相同" in result.reason
    result = decider.select_card(state(("review-b", 1), ("review-a", 1), recommended=0))
    assert result.action.args["pick_indexes"] == [0]


def test_trace_restored_picks_count_as_owned_without_full_deck(route):
    decider, _ = route
    decider.picked_musts.add("review-a")
    result = decider.select_card(state(("review-a", 0), ("review-b", 0)))
    assert result.action.args["pick_indexes"] == [1]


def test_without_recommendation_compatible_known_card_metadata_can_decide(route, monkeypatch):
    decider, idol = route
    idol["planType"] = "ProducePlanType_Plan2"
    rows = {
        "common-r": {"planType": "ProducePlanType_Common", "rarity": "ProduceCardRarity_R", "effectGroupIds": []},
        "same-sr": {"planType": "ProducePlanType_Plan2", "rarity": "ProduceCardRarity_Sr", "effectGroupIds": []},
        "wrong-ssr": {"planType": "ProducePlanType_Plan1", "rarity": "ProduceCardRarity_Ssr", "effectGroupIds": []},
    }
    monkeypatch.setattr(context, "catalog", lambda: NS(one=lambda *a: idol, card=lambda cid, upgrade: rows[cid]))
    result = decider.select_card(state(("common-r", 1), ("same-sr", 1), ("wrong-ssr", 1)))
    assert result.action.args["pick_indexes"] == [1]
    assert "同路线或通用卡" in result.reason


@pytest.mark.parametrize("cards", [[("yaruki-must", 1)], [("unknown", 1)], [("review-a", None)]])
def test_no_verified_recommended_candidate_waits_without_reroll(route, cards):
    decider, _ = route
    assert decider.select_card(state(*cards)).action.kind is ActionKind.WAIT
    assert decider._page_spend == {}


def test_unknown_idol_effect_waits_and_error_fallback_does_not_apply_other_route(route):
    decider, idol = route
    idol["examEffectType"] = "ProduceExamEffectType_Unknown"
    current = state(("yaruki-must", 1))
    assert decider.select_card(current).action.kind is ActionKind.WAIT
    assert decider._page_fallback("SELECT_CARD", current, 1, "test").action.kind is ActionKind.WAIT


@pytest.mark.parametrize("enabled,effect", [
    (False, "ProduceExamEffectType_ExamReview"),
    (True, "ProduceExamEffectType_ExamCardPlayAggressive"),
])
def test_flag_off_and_known_yaruki_keep_existing_path(route, monkeypatch, enabled, effect):
    decider, idol = route
    if not enabled:
        monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    idol["examEffectType"] = effect
    monkeypatch.setattr(decider, "_select_card_for_selected_idol", lambda *a: pytest.fail("Must use existing path"))
    # No candidates returns the existing conservative no-recognition branch.
    assert decider.select_card(state()).action.kind is ActionKind.WAIT
