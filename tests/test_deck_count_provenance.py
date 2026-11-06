"""牌组张数只由完整牌组基线及可核实的卡事件维护。"""

from hiro.contracts import Event, GameState, Observation, TraceWriter
from hiro.contracts.observation import PageObs
from hiro.loop.events import apply_event, confirmed_deck_size
from hiro.loop.reduce import reduce
from hiro.loop.session import Session


def card(cid):
    return {"card_id": cid, "upgrade": 0}


def review(*cards):
    return Event(seq=1, kind="DECK_REVIEW", origin="review", confirmed=True,
                 args={"deck": [card(c) for c in cards], "deck_size": len(cards)})


def action(seq, kind, **args):
    return Event(seq=seq, kind=kind, origin="action", args=args, ref={"decision_seq": seq})


def test_event_chain_updates_known_count_add_delete_change():
    state, _ = apply_event(GameState(), review("a", "b"), predictor=lambda *_: [])
    assert state.produce["deck_size"] == 2 and state.field_status["produce.deck"] == "verified"
    for event, expected in ((action(2, "CARD_ACQUIRE", card_id="c"), 3),
                            (action(3, "CARD_DELETE", card_id="a"), 2),
                            (action(4, "CARD_CHANGE", remove_card_id="b", card_id="d"), 2)):
        state, _ = apply_event(state, event, predictor=lambda *_: [])
        assert state.produce["deck_size"] == expected == len(state.produce["deck"])
    assert [c["card_id"] for c in state.produce["deck"]] == ["c", "d"]


def test_unknown_initial_or_incomplete_change_never_claims_size():
    state = GameState(produce={"deck": [card("a")], "deck_size": 1})
    state, _ = apply_event(state, action(2, "CARD_ACQUIRE", card_id="b"), predictor=lambda *_: [])
    assert len(state.produce["deck"]) == 2 and state.produce["deck_size"] is None
    assert state.field_status["produce.deck"] == "pending"

    state, _ = apply_event(GameState(), review("a", "b"), predictor=lambda *_: [])
    state, _ = apply_event(state, action(3, "CARD_CHANGE", remove_card_id="a"), predictor=lambda *_: [])
    assert state.produce["deck_size"] is None and state.field_status["produce.deck"] == "pending"


def test_acquire_popup_pairs_once_and_confirms_count(tmp_path):
    session = Session(TraceWriter(tmp_path), shoot=lambda: None, classify=lambda: ("ACQUIRE", "produce"), extract=lambda *_: ({}, 0))
    session.state, _ = apply_event(GameState(), review("a"), predictor=lambda *_: [])
    session.emit(action(2, "CARD_ACQUIRE", card_id="b"))
    assert session.state.produce["deck_size"] == 2 and session.state.field_status["produce.deck"] == "predicted"
    session.emit(Event(seq=3, kind="CARD_ACQUIRE", origin="observed", confirmed=True, args={"card_id": "b"}))
    assert len(session.state.produce["deck"]) == session.state.produce["deck_size"] == 2
    assert session.state.field_status["produce.deck"] == "verified"


def test_complete_deck_observation_repeats_without_counting_twice():
    obs = Observation(seq=1, t=0, page=PageObs("DECK_LIST", "produce", 1.0, 2), source="screen",
                      fields={"deck": [card("a"), card("b")], "deck_size": 2, "complete": True})
    state = reduce(GameState(), obs)
    state = reduce(state, Observation(seq=2, t=0, page=obs.page, source="screen", fields=obs.fields))
    assert len(state.produce["deck"]) == state.produce["deck_size"] == 2
    assert state.field_status["produce.deck"] == "verified"
    incomplete = reduce(state, Observation(seq=3, t=0, page=obs.page, source="screen",
                                           fields={"deck": [card("a")], "deck_size": 2, "complete": False}))
    assert incomplete.produce["deck_size"] == 2 and len(incomplete.produce["deck"]) == 2


def test_historical_count_requires_review_and_skips_paired_observation():
    deck = [card("b"), card("c")]
    steps = [{"events": [review("a", "b").to_dict()]},
             {"execution": {"ok": True}, "events": [action(2, "CARD_ACQUIRE", card_id="c").to_dict()]},
             {"events": [Event(seq=3, kind="CARD_ACQUIRE", origin="observed", confirmed=True,
                               args={"card_id": "c"}, ref={"paired": 2}).to_dict()]},
             {"execution": {"ok": True}, "events": [action(4, "CARD_DELETE", card_id="a").to_dict()]},
             {"events": [Event(seq=5, kind="CARD_DELETE", origin="observed", confirmed=True,
                               args={"card_id": "a"}, ref={"paired": 4}).to_dict()]}]
    assert confirmed_deck_size(steps, deck) == 2
    assert confirmed_deck_size(steps[1:], deck) is None
    assert confirmed_deck_size(steps, [*deck, card("extra")]) is None
    assert confirmed_deck_size(steps[:-1], deck) is None  # 成功点击但还没观察到删除确认
    bad = [*steps, {"events": [Event(seq=6, kind="CARD_ACQUIRE", origin="observed", confirmed=True,
                                      args={}).to_dict()]}]
    assert confirmed_deck_size(bad, deck) is None
    bad_change = [*steps, {"events": [Event(seq=6, kind="CARD_CHANGE", origin="observed", confirmed=True,
                                             args={"remove_card_id": "missing", "card_id": "c"}).to_dict()]}]
    assert confirmed_deck_size(bad_change, deck) is None
    cross_segment = [steps[0], steps[1], {"_segment_start": "next"}, steps[2], *steps[3:]]
    assert confirmed_deck_size(cross_segment, deck) is None
