"""Count proof, exact versions and customization are separate evidence."""
from hiro.contracts import Event, GameState
from hiro.loop.events import apply_event, confirmed_deck_size


def apply(state, kind, **args):
    return apply_event(state, Event(seq=8, kind=kind, origin="observed", confirmed=True, args=args),
                       predictor=lambda *_: [])[0]


def reviewed(deck):
    return apply(GameState(), "DECK_REVIEW", deck=deck, deck_size=len(deck))


def test_review_preserves_customization_flags_without_fabricating_effects():
    state = reviewed([{"card_id": "custom", "upgrade": 1, "customized": True},
                      {"card_id": "plain", "upgrade": 0, "customized": False}])
    assert state.produce["deck"] == [{"card_id": "custom", "upgrade": 1, "customized": True},
                                     {"card_id": "plain", "upgrade": 0, "customized": False}]
    assert state.field_status["produce.deck"] == "verified"
    assert all("master_effect_text" not in c for c in state.produce["deck"])


def test_review_unknown_upgrade_stays_unknown_and_requires_review():
    state = reviewed([{"card_id": "unknown-version", "upgrade": None}])
    assert state.produce["deck"][0]["upgrade"] is None
    assert state.field_status["produce.deck"] == "pending"
    assert state.produce["deck_size"] is None
    assert "produce.deck" in state.pending_review


def test_exact_unique_upgrade_preserves_other_versions_and_count_proof():
    state = reviewed([{"card_id": "a", "upgrade": 0}, {"card_id": "a", "upgrade": 1}])
    upgraded = apply(state, "CARD_UPGRADE", card_id="a", upgrade=1)
    assert [c["upgrade"] for c in upgraded.produce["deck"]] == [1, 1]
    assert upgraded.field_status["produce.deck"] == "verified"
    assert upgraded.produce["deck_size"] == 2 and not upgraded.pending_review
    # A known + -> ++ transition must not be rewritten as 0 -> +.
    second = reviewed([{"card_id": "a", "upgrade": 1}])
    assert apply(second, "CARD_UPGRADE", card_id="a", upgrade=2).produce["deck"][0]["upgrade"] == 2


def test_duplicate_or_missing_upgrade_target_does_not_pick_first_or_change_count():
    for deck, identity in (([{"card_id": "a", "upgrade": 0}] * 2, "a"),
                           ([{"card_id": "a", "upgrade": 1}], "a"),
                           ([{"card_id": "a", "upgrade": 0}], "absent")):
        state = reviewed(deck)
        result = apply(state, "CARD_UPGRADE", card_id=identity, upgrade=1)
        assert result.produce["deck"] == state.produce["deck"]
        assert result.produce["deck_size"] == len(deck)
        assert result.field_status["produce.deck_size"] == "verified"
        assert result.field_status["produce.deck"] == "pending"
        assert "produce.deck" in result.pending_review


def test_customize_marks_exact_owned_version_unknown_without_changing_upgrade():
    state = reviewed([{"card_id": "a", "upgrade": 0}, {"card_id": "a", "upgrade": 1}])
    result = apply(state, "CARD_CUSTOMIZE", card_id="a", upgrade=1)
    assert "customized" not in result.produce["deck"][0]
    assert result.produce["deck"][1] == {"card_id": "a", "upgrade": 1, "customized": True,
                                        "customization_effects_known": False}
    assert result.produce["deck_size"] == 2
    assert result.field_status["produce.deck"] == "pending" and "produce.deck" in result.pending_review
    assert state.produce["deck"][1] == {"card_id": "a", "upgrade": 1}


def test_ambiguous_customize_never_claims_which_copy_changed():
    state = reviewed([{"card_id": "a", "upgrade": 0}] * 2)
    result = apply(state, "CARD_CUSTOMIZE", card_id="a", upgrade=0)
    assert result.produce["deck"] == state.produce["deck"]
    assert result.field_status["produce.deck"] == "pending"
    assert result.produce["deck_size"] == 2


def test_historical_count_proof_makes_no_version_or_effect_claim():
    review = Event(seq=1, kind="DECK_REVIEW", origin="review", confirmed=True,
                   args={"deck": [{"card_id": "a", "upgrade": 0}], "deck_size": 1})
    upgrade = Event(seq=2, kind="CARD_UPGRADE", origin="observed", confirmed=True,
                    args={"card_id": "a", "upgrade": 1})
    customize = Event(seq=3, kind="CARD_CUSTOMIZE", origin="observed", confirmed=True,
                      args={"card_id": "a", "upgrade": 1})
    steps = [{"events": [event.to_dict()]} for event in (review, upgrade, customize)]
    # It proves the same count even if the supplied version/customization is stale.
    assert confirmed_deck_size(steps, [{"card_id": "a", "upgrade": 0}]) == 1
    assert confirmed_deck_size(steps, [{"card_id": "a", "upgrade": 1, "customized": True}]) == 1
    assert confirmed_deck_size(steps, [{"card_id": "other", "upgrade": 1}]) is None



def test_enhance_action_source_zero_normalizes_to_target_one_end_to_end():
    from hiro.contracts import Action, ActionKind
    from hiro.loop.events import events_from_step
    state = reviewed([{"card_id": "a", "upgrade": 0}])
    action = Action(ActionKind.ENHANCE_CARD, {"card_id": "a", "index": 3, "upgrade": 0})
    events = events_from_step("SKILL_CARD_ENHANCE", action.to_dict(), True, {}, state.produce, seq=9)
    assert len(events) == 1 and events[0].args == {
        "card_id": "a", "upgrade": 1, "from_upgrade": 0, "source": "event"}
    after, _ = apply_event(state, events[0], predictor=lambda *_: [])
    assert after.produce["deck"] == [{"card_id": "a", "upgrade": 1}]
    assert after.produce["deck_size"] == 1
    assert after.field_status["produce.deck"] == "verified" and not after.pending_review


def test_unknown_enhance_source_does_not_guess_target_one():
    from hiro.contracts import Action, ActionKind
    from hiro.loop.events import events_from_step
    state = reviewed([{"card_id": "a", "upgrade": 0}])
    for source in (None, True, "0", -1):
        action = Action(ActionKind.ENHANCE_CARD, {"card_id": "a", "upgrade": source})
        events = events_from_step("SKILL_CARD_ENHANCE", action.to_dict(), True, {}, state.produce, seq=9)
        assert len(events) == 1
        assert "upgrade" not in events[0].args and "from_upgrade" not in events[0].args
        after, _ = apply_event(state, events[0], predictor=lambda *_: [])
        assert after.produce["deck"] == state.produce["deck"]
        assert after.produce["deck_size"] == 1
        assert after.field_status["produce.deck"] == "pending" and "produce.deck" in after.pending_review
    # An observed event with no target version is equally unknown.
    assert apply(state, "CARD_UPGRADE", card_id="a").field_status["produce.deck"] == "pending"


def test_observed_upgrade_target_semantics_remain_unchanged():
    state = reviewed([{"card_id": "a", "upgrade": 0}])
    after = apply(state, "CARD_UPGRADE", card_id="a", upgrade=1)
    assert after.produce["deck"][0]["upgrade"] == 1
