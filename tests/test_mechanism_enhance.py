import json
from types import SimpleNamespace

import pytest

from hiro.brain import mechanism_enhance as module, route_guard
from hiro.brain.llm import MockLLM
from hiro.contracts import ActionKind, GameState


class Master:
    def one(self, table, identity):
        assert table == "IdolCard"
        return {"id": identity, "name": identity, "examEffectType": "Review" if identity == "one" else "Buff"}

    def card(self, identity, upgrade):
        return {"id": identity, "name": identity, "category": "ProduceCardCategory_Mental",
                "produceDescriptions": [{"text": f"{identity} effect version {upgrade}"}]}


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_ENHANCE", "1")
    monkeypatch.setattr(module, "catalog", Master)
    return GameState(produce={"mode": "produce-007", "step": 14}, page_fields={"trigger": "pitem", "cancelable": False,
        "cards": [{"index": 4, "card_id": "a", "upgrade": 0}, {"index": 7, "card_id": "b", "upgrade": 0}]})


def decider(reply):
    llm = MockLLM([reply])
    def ask(prompts, payload):
        result = llm.ask_json("test", json.dumps(payload))
        return result.data, [result.record()]
    return SimpleNamespace(llm=llm, _ask=ask)


@pytest.mark.parametrize("identity", ["one", "two"])
def test_different_idol_mechanisms_and_exact_upgrade_delta(state, identity):
    d = decider({"action": "enhance", "index": 7, "reason": "upgrade delta fits engine"})
    result = module.compare(d, state, identity)
    assert result.action.args == {"card_id": "b", "index": 7, "upgrade": 0}
    payload = json.loads(d.llm.calls[0][1])
    assert payload["idol"]["id"] == identity
    assert payload["candidates"][1]["before"]["master_effect_text"] == "b effect version 0"
    assert payload["candidates"][1]["after"]["master_effect_text"] == "b effect version 1"
    assert payload["deck"]["complete"] is False


@pytest.mark.parametrize("reply", [{"action": "cancel", "reason": "no"}, {"action": "enhance", "index": True, "reason": "bad"},
    {"action": "enhance", "index": 0, "reason": "bad"}, {"action": "enhance", "index": 4, "reason": "x", "service": "upgrade"}, RuntimeError("failed")])
def test_forced_invalid_or_failed_choice_waits(state, reply):
    assert module.compare(decider(reply), state, "one").action.kind is ActionKind.WAIT


@pytest.mark.parametrize("cancelable,expected", [(True, ActionKind.ENHANCE_CARD), (False, ActionKind.WAIT), (None, ActionKind.WAIT)])
def test_event_cancel_semantics(state, cancelable, expected):
    state.page_fields.update(trigger=None, enhance_origin="event", cancelable=cancelable)
    result = module.compare(decider({"action": "cancel", "reason": "no useful gain"}), state, "one")
    assert result.action.kind is expected
    if cancelable is True:
        assert result.action.args == {"cancel": True}


@pytest.mark.parametrize("fields", [{}, {"price": 0, "trigger": "pitem"}, {"price": 100, "enhance_origin": "event"},
                                    {"confirm": {"price": 10}, "trigger": "pitem"}, {"services": {"upgrade": {}}, "trigger": "pitem"}])
def test_paid_or_unknown_origin_preserves_old_guard(state, monkeypatch, fields):
    state.page_fields = {"cards": state.page_fields["cards"], **fields}
    sentinel = object()
    monkeypatch.setattr(route_guard, "_enhance", lambda *a: sentinel)
    d = SimpleNamespace(profile=None, idol_card_id="one", _uses_yaruki_policy=lambda _: False)
    assert route_guard.guard(d, "SKILL_CARD_ENHANCE", state) is sentinel


def test_default_off_uses_old_guard(state, monkeypatch):
    monkeypatch.delenv("HIRO_MECHANISM_ENHANCE")
    assert not module.applicable(state)


def test_duplicate_card_id_and_unknown_upgrade_never_reach_model(state):
    state.page_fields["cards"] = [{"index": 0, "card_id": "a", "upgrade": 0},
                                  {"index": 1, "card_id": "a", "upgrade": 1},
                                  {"index": 2, "card_id": "b", "upgrade": None}]
    d = decider({"action": "enhance", "index": 0, "reason": "x"})
    assert module.compare(d, state, "one").action.kind is ActionKind.WAIT
    assert not d.llm.calls


def test_no_model_obeys_cancelability(state):
    assert module.compare(SimpleNamespace(llm=None), state, "one").action.kind is ActionKind.WAIT
    state.page_fields.update(trigger=None, enhance_origin="event", cancelable=True)
    assert module.compare(SimpleNamespace(llm=None), state, "one").action.args == {"cancel": True}
