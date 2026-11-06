import json
from types import SimpleNamespace
import pytest
from hiro.brain import mechanism_change as module
from hiro.brain.llm import MockLLM
from hiro.contracts import ActionKind, GameState

class Master:
    def one(self, table, identity):
        return {"id": identity, "examEffectType": "effect-" + identity}
    def card(self, identity, upgrade):
        return {"name": identity, "category": "ProduceCardCategory_Mental",
                "produceDescriptions": [{"text": f"{identity} exact effect {upgrade}"}]}

@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_CHANGE", "1")
    monkeypatch.setattr(module, "catalog", Master)
    monkeypatch.setattr(module, "protected_card_ids", lambda: {"protected"})
    return GameState(produce={"mode": "qualify", "step": 17, "deck_size": 4, "deck": [
        {"card_id": "old", "upgrade": 0}, {"card_id": "old", "upgrade": 1},
        {"card_id": "duplicate", "upgrade": 0}, {"card_id": "duplicate", "upgrade": 0}]},
        field_status={"produce.deck": "verified", "produce.deck_size": "verified"},
        page_fields={"candidates": [{"index": 7, "center": [362, 900], "card_id": "new", "upgrade": 0}]})

def decider(replies):
    llm = MockLLM(replies)
    def ask(prompts, payload):
        assert prompts == ["mechanism_change.md"]
        result = llm.ask_json("test", json.dumps(payload))
        return result.data, [result.record()]
    return SimpleNamespace(llm=llm, _ask=ask)

@pytest.mark.parametrize("identity", ["one", "two"])
def test_two_stages_preserve_exact_pair_and_inherited_upgrade(state, identity):
    d = decider([{"action": "change", "pair_id": 1, "reason": "compare effects"},
                 {"action": "confirm", "reason": "same original pair"}])
    first = module.compare(d, state, identity, 1)
    assert first.action.args["pick_column"] == 1
    payload = json.loads(d.llm.calls[0][1])
    assert len(payload["pairs"]) == 2
    assert payload["pairs"][1]["incoming_after_change"]["master_effect_text"] == "new exact effect 1"
    state.page_fields = {"cards": [dict(c, index=i) for i,c in enumerate(state.produce["deck"])], "deck_complete": True}
    second = module.compare(d, state, identity, 2)
    assert second.action.args == {"stage": 2, "remove_card_id": "old", "remove_upgrade": 1,
                                  "card_id": "new", "upgrade": 1, "strict": True}
    assert json.loads(d.llm.calls[1][1])["selected_pair"] == payload["pairs"][1]
    from hiro.loop.events import events_from_step, apply_event
    events = events_from_step("SKILL_CARD_CHANGE_2", second.action.to_dict(), True,
                              state.page_fields, state.produce, seq=20)
    assert len(events) == 1 and events[0].args["upgrade"] == 1
    after, _ = apply_event(state, events[0])
    assert after.produce["deck"] == [{"card_id":"old", "upgrade":0},
        {"card_id":"duplicate", "upgrade":0}, {"card_id":"duplicate", "upgrade":0},
        {"card_id":"new", "upgrade":1}]
    assert after.produce["deck_size"] == 4


def test_change_ledger_does_not_remove_wrong_version_or_append_phantom(state):
    from hiro.contracts import Event
    from hiro.loop.events import apply_event
    e = Event(seq=20, kind="CARD_CHANGE", origin="action", args={"remove_card_id":"old",
        "remove_upgrade":2, "card_id":"new", "upgrade":2}, ref={"decision_seq":20})
    after, _ = apply_event(state, e)
    assert after.produce["deck"] == state.produce["deck"]
    assert "produce.deck" in after.pending_review

@pytest.mark.parametrize("reply", [{"action":"cancel", "reason":"no"}, {"action":"change","pair_id":True,"reason":"x"},
    {"action":"change","pair_id":99,"reason":"x"}, {"action":"change","pair_id":0,"reason":"x","reroll":True},
    {"action":"wait","reason":"uncertain"}, RuntimeError("failure")])
def test_invalid_uncertain_and_failed_replies_wait(state, reply):
    assert module.compare(decider([reply]), state, "one", 1).action.kind is ActionKind.WAIT

@pytest.mark.parametrize("change", ["incomplete", "protected", "customized", "unknown_version"])
def test_readiness_requires_evidence_and_real_outgoing(state, change):
    if change == "incomplete": state.field_status["produce.deck"] = "unknown"
    elif change == "protected":
        for c in state.produce["deck"]: c["card_id"] = "protected"
    elif change == "customized":
        for c in state.produce["deck"]: c["customized"] = True
    else: state.produce["deck"][0]["upgrade"] = None
    assert not module.readiness(state, "one")

@pytest.mark.parametrize("change", ["deck", "stage", "identity", "incomplete"])
def test_stage_two_never_replaces_target(state, change):
    d = decider([{"action":"change","pair_id":0,"reason":"x"}])
    module.compare(d, state, "one", 1)
    state.page_fields = {"cards": [dict(c, index=i) for i,c in enumerate(state.produce["deck"])], "deck_complete": True}
    if change == "deck": state.page_fields["cards"][0]["upgrade"] = 1
    elif change == "stage": state.produce["step"] = 18
    elif change == "incomplete": state.page_fields["deck_complete"] = False
    result = module.compare(d, state, "two" if change == "identity" else "one", 2)
    assert result.action.kind is ActionKind.WAIT
    assert len(d.llm.calls) == 1

def test_default_off_and_no_model(state, monkeypatch):
    assert module.readiness(state, "one")
    assert module.compare(SimpleNamespace(llm=None),state,"one",1).action.kind is ActionKind.WAIT
    monkeypatch.delenv("HIRO_MECHANISM_CHANGE")
    assert not module.enabled()
    assert not module.readiness(state,"one")


def test_stage2_resume_reassesses_only_observed_incoming_and_complete_current_deck(state):
    state.page_fields = {"deck_complete": True, "cards": list(state.produce["deck"]),
                         "incoming_card": {"card_id":"new", "upgrade":0}}
    d = decider([{"action":"change", "pair_id":1, "reason":"fresh complete scan comparison"}])
    result = module.compare(d, state, "one", 2)
    assert result.action.kind == ActionKind.CHANGE_CARD
    assert result.action.args["remove_upgrade"] == 1
    assert result.action.args["card_id"] == "new"
    assert result.action.args["upgrade"] == 1
    assert json.loads(d.llm.calls[0][1])["reassessment"] is True


@pytest.mark.parametrize("missing", ["incoming", "complete", "review", "matches"])
def test_stage2_resume_never_invents_missing_evidence(state, missing):
    state.page_fields = {"deck_complete": True, "cards": list(state.produce["deck"]),
                         "incoming_card": {"card_id":"new", "upgrade":0}}
    if missing == "incoming": state.page_fields.pop("incoming_card")
    elif missing == "complete": state.page_fields["deck_complete"] = False
    elif missing == "review": state.field_status["produce.deck"] = "pending"
    else: state.page_fields["cards"] = state.page_fields["cards"][:-1]
    d = decider([])
    assert module.compare(d, state, "one", 2).action.kind == ActionKind.WAIT
    assert not d.llm.calls

@pytest.mark.parametrize("cards,protected,upgrade", [
    ([{"card_id":"a","upgrade":0}], set(), 1),
    ([{"card_id":"a","upgrade":0},{"card_id":"a","upgrade":0}], set(), 0),
    ([{"card_id":"a","upgrade":0}], {"a"}, 0),
    ([{"card_id":"a","upgrade":None}], set(), 0),
])
def test_strict_executor_never_falls_back(cards, protected, upgrade):
    from hiro.loop.kaa_patches import pick_change_target
    assert pick_change_target(cards,card_id="a",remove_upgrade=upgrade,protected=protected,strict=True)[0] is None

@pytest.mark.parametrize("selected,expected_next", [(None, False), (0, True)])
def test_strict_stage1_checks_actual_selection_before_next(monkeypatch, selected, expected_next):
    from unittest.mock import MagicMock
    from hiro.loop import kaa_patches as kp
    from hiro.vision import deck
    from kaa.tasks import R
    import numpy as np
    dev = MagicMock()
    dev.screenshot.return_value = np.zeros((1280,720,3),dtype=np.uint8)
    monkeypatch.setattr(kp,"device",dev)
    monkeypatch.setattr(kp.time,"sleep",lambda _:None)
    monkeypatch.setattr(kp,"_change_run",lambda:SimpleNamespace(snap=lambda *a:None))
    monkeypatch.setattr(kp,"_mark_card_name",lambda *a:"a")
    monkeypatch.setattr(kp,"find_card_marks",lambda *a:[SimpleNamespace(rect=SimpleNamespace(x1=213))])
    c={"index":0,"card_id":"a","center":[223,900]}
    monkeypatch.setattr(deck,"read_change_candidates",lambda _: {"candidates":[c],"selected":selected})
    exists=MagicMock(side_effect=[False,False,True])
    monkeypatch.setattr(R.InProduce.DialogCardChange2.Title,"exists",exists)
    button=MagicMock()
    button.q.return_value.try_click.return_value=True
    monkeypatch.setattr(R.InProduce.DialogCardChange1,"ButtonNext",button)
    assert kp.change_stage1(None,0,strict=True,expected_card_id="a") is expected_next
    assert button.q.called is expected_next
    assert dev.click.call_count == (0 if selected == 0 else 1)
