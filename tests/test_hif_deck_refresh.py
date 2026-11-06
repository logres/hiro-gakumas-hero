import json
from types import SimpleNamespace

from hiro.contracts import Event, GameState
from hiro.loop.events import apply_event
from hiro.produce.hif import HiroHifStrategy


class Session:
    def __init__(self, state):
        self.state, self.events = state, []
        self.trace = SimpleNamespace(next_seq=lambda: 10, record_initial_state=lambda _: None)
    def emit(self, event):
        self.events.append(event)
        self.state, _ = apply_event(self.state, event, predictor=lambda *_: [])
    def note(self, _):
        pass


def strategy(state):
    result = object.__new__(HiroHifStrategy)
    result.s = Session(state)
    return result


def test_resume_count_proof_does_not_promote_versions(monkeypatch, tmp_path):
    monkeypatch.setenv("HIRO_DECK_REVIEW", "1")
    cards = [{"card_id":"a", "upgrade":0}]
    event = Event(seq=1, kind="DECK_REVIEW", origin="review", confirmed=True,
                  args={"deck":cards, "deck_size":1})
    row = {"seq":1, "state":{"produce":{"deck":cards,"deck_size":1}}, "events":[event.to_dict()]}
    (tmp_path / "steps.jsonl").write_text(json.dumps(row)+"\n", encoding="utf8")
    obj = strategy(GameState())
    obj._prior_trace_dirs = lambda: [tmp_path]
    obj._seed_produce_from_trace()
    assert obj.s.state.produce["deck_size"] == 1
    assert obj.s.state.field_status["produce.deck_size"] == "verified"
    assert obj.s.state.field_status["produce.deck"] == "pending"
    assert "produce.deck" in obj.s.state.pending_review


def test_exam_refresh_invalidates_old_completeness_without_fabricating_changes(monkeypatch):
    monkeypatch.setenv("HIRO_DECK_REVIEW", "1")
    obj = strategy(GameState(produce={"deck":[{"card_id":"a","upgrade":0}], "deck_size":1},
                             field_status={"produce.deck":"verified"}))
    obj._require_deck_review("exam boundary")
    assert obj.s.state.produce["deck"] == [{"card_id":"a","upgrade":0}]
    assert obj.s.state.field_status["produce.deck"] == "pending"
    assert obj.s.events[0].args == {"field":"produce.deck", "reason":"exam boundary"}


def test_complete_change_scan_replaces_stale_inventory_and_keeps_customization(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_CHANGE", "1")
    cards = [{"card_id":"actual", "upgrade":1, "customized":True}]
    obj = strategy(GameState(produce={"deck":[{"card_id":"stale","upgrade":0}], "deck_size":1},
                             page_fields={"cards":cards,"deck_complete":False}))
    obj._accept_change_deck_review()
    assert not obj.s.events
    obj.s.state.page_fields["deck_complete"] = True
    obj._accept_change_deck_review()
    assert obj.s.state.produce["deck"] == cards
    assert obj.s.state.field_status["produce.deck"] == "verified"
    assert obj.s.events[0].confirmed is True
