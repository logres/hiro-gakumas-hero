"""Synthetic interval contracts; no game, real model or account data."""
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest

from hiro.brain import mechanism_interval as module
from hiro.brain.llm import MockLLM
from hiro.contracts import Action, ActionKind, Decision, ExecutionResult, GameState
from hiro.contracts.game_state import PageState, Source
from hiro.state.catalog import Catalog


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_INTERVAL", "1")
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE IdolCard(id TEXT,name TEXT); CREATE TABLE ProduceCard(id TEXT,upgradeCount INT,name TEXT,produceDescriptions TEXT); CREATE TABLE ProduceDrink(id TEXT,name TEXT,produceDescriptions TEXT);")
    db.executemany("INSERT INTO IdolCard VALUES (?,?)", [("one", "One"), ("two", "Two")])
    db.execute("INSERT INTO ProduceCard VALUES ('card',1,'Card',?)", (json.dumps([{"text": "Exact upgraded effect"}]),))
    db.execute("INSERT INTO ProduceDrink VALUES ('drink','Drink',?)", (json.dumps([{"text": "Draw two"}]),))
    cat = Catalog(db)
    monkeypatch.setattr("hiro.state.catalog.catalog", lambda: cat)
    produce = dict(produce_point=100, stamina=17, max_stamina=33, drinks=[], drink_capacity=4)
    state = GameState(seq=9, page=PageState(name="HIF_ROUND_INTERVAL"), produce=produce,
                      page_fields={"complete": True, **produce, "interval": {
                          "cards": [{"index": 2, "card_id": "card", "upgrade": 1, "price": 70, "purchased": False}],
                          "drinks": [{"index": 6, "drink_id": "drink", "price": 50, "purchased": False}],
                          "recover": {"available": True, "price_per_2hp": 10}}},
                      sources={"produce." + k: Source("screen", 9) for k in produce},
                      field_status={"produce." + k: "observed" for k in produce})
    yield state, cat
    db.close()


def decider(reply):
    llm = MockLLM([reply])
    def ask(prompts, payload):
        result = llm.ask_json("test", json.dumps(payload))
        return result.data, [result.record()]
    return NS(llm=llm, _ask=ask)


@pytest.mark.parametrize("identity", ["one", "two"])
def test_mechanisms_and_execution_indices(setup, identity):
    state, master = setup
    payload = module.build_context(state, identity, master)
    assert payload["idol"]["id"] == identity
    assert [(c["index"], c["kind"]) for c in payload["candidates"] if "index" in c] == [(2, "card"), (6, "drink")]
    assert payload["candidates"][0]["master_effect_text"] == "Exact upgraded effect"
    assert payload["deck"]["absence_claim_allowed"] is False
    assert "22" in payload["limitations"]
    d = module.compare(decider({"action": "buy", "index": 2, "reason": "effect"}), state, identity)
    assert d.action == Action(ActionKind.INTERVAL_BUY, {"index": 2})


def test_recovery_targets_cost_and_capacity(setup):
    state, master = setup
    state.produce["drinks"] = ["drink"] * 4
    state.page_fields["drinks"] = state.produce["drinks"]
    payload = module.build_context(state, "one", master)
    assert not any(c["kind"] == "drink" for c in payload["candidates"])
    recover = [c for c in payload["candidates"] if c["kind"] == "recover"]
    assert recover[0]["target_hp"] == 19 and recover[0]["price"] == 10
    assert recover[-1]["target_hp"] == 33 and recover[-1]["price"] == 80
    d = module.compare(decider({"action": "recover", "target_hp": 21, "reason": "budget"}), state, "one")
    assert d.action.args == {"service": "recover", "target_hp": 21}


@pytest.mark.parametrize("reply", [{"action": "buy", "index": True, "reason": "x"},
    {"action": "buy", "index": 4, "reason": "x"}, {"action": "recover", "target_hp": 18, "reason": "x"},
    {"action": "recover", "target_hp": 19, "reason": "x", "jewel": True},
    {"action": "upgrade", "index": 2, "reason": "x"}, {"action": "end", "reason": ""}])
def test_output_whitelist(setup, reply):
    assert module.compare(decider(reply), setup[0], "one").action.kind is ActionKind.INTERVAL_END


@pytest.mark.parametrize("patch", ["stale", "pending", "incomplete", "budget", "jewel", "price"])
def test_unknown_or_illegal_never_spends(setup, patch):
    state, master = setup
    if patch == "stale":
        state.sources["produce.produce_point"] = Source("screen", 8)
    elif patch == "pending":
        state.pending_review.append("produce.produce_point")
    elif patch == "incomplete":
        state.page_fields["complete"] = False
    elif patch == "budget":
        state.produce["produce_point"] = state.page_fields["produce_point"] = 0
    else:
        for key in ("cards", "drinks"):
            state.page_fields["interval"][key][0].update({"jewel": True} if patch == "jewel" else {"price": None})
        state.page_fields["interval"]["recover"]["price_per_2hp"] = 11
    d = decider({"action": "buy", "index": 2, "reason": "x"})
    assert module.compare(d, state, "one").action.kind is ActionKind.INTERVAL_END
    assert not d.llm.calls


def test_repeat_budget_not_reused(setup):
    state, _ = setup
    d = decider({"action": "buy", "index": 2, "reason": "effect"})
    assert module.compare(d, state, "one").action.kind is ActionKind.INTERVAL_BUY
    assert module.compare(d, state, "one").action.kind is ActionKind.INTERVAL_END
    state.seq += 1
    for source in state.sources.values():
        source.seq = state.seq
    assert module.compare(d, state, "one").action.kind is ActionKind.INTERVAL_END
    assert len(d.llm.calls) == 1


def test_disabled_no_model_and_guard_dispatch(setup, monkeypatch):
    from hiro.brain.route_guard import guard
    state, _ = setup
    d = decider({"action": "end", "reason": "enough"})
    d.idol_card_id = "one"
    d._uses_yaruki_policy = lambda _: False
    assert guard(d, "HIF_ROUND_INTERVAL", state).decider == "mechanism_interval"
    monkeypatch.delenv("HIRO_MECHANISM_INTERVAL")
    assert guard(d, "HIF_ROUND_INTERVAL", state).decider == "route_guard:hif_round_interval"


@pytest.mark.parametrize("kind", [ActionKind.INTERVAL_END, ActionKind.WAIT])
def test_generic_end_or_exhausted_wait_has_no_implicit_consumption(kind):
    from hiro.produce.interval import interval_loop
    calls = []
    def execute(action, fields):
        calls.append(action)
        return ExecutionResult(action=action, ok=True)
    def status():
        pytest.fail("Generic ending must not consult legacy HP target or budget")
    d = Decision(Action(kind), "done", "rule")
    assert interval_loop(lambda: {}, lambda _: d, execute=execute, status=status,
                         implicit_recovery=False, max_steps=2)
    assert calls == [Action(ActionKind.INTERVAL_END)]


def test_generic_missing_shelf_does_not_reuse_previous_observation():
    from hiro.produce.interval import interval_loop
    frames = iter([{"interval": {"cards": [{"index": 0}]}, "complete": True}, {"complete": False}])
    seen = []
    def decide(fields):
        seen.append(fields)
        return Decision(Action(ActionKind.WAIT), "reread", "rule")
    interval_loop(lambda: next(frames), decide, max_steps=2, implicit_recovery=False,
                  execute=lambda action, fields: ExecutionResult(action=action, ok=True))
    assert not seen[1].get("interval")


def test_purchase_confirmation_cancels_jewels_before_confirm(monkeypatch):
    from hiro.produce import shop
    taps = []
    boxes = [("ジュエル", .99, (10, 10, 100, 30))]
    run = NS(shoot=lambda: object(), snap=lambda *a: None, ocr=lambda _: boxes,
             tap=taps.append, wait=lambda *a, **k: NS(changed=True, img=object()),
             until=lambda *a, **k: (True, object()),
             result=lambda ok, error=None, **k: NS(ok=ok, error=error))
    monkeypatch.setattr(shop, "read_p", lambda *a: 100)
    monkeypatch.setattr(shop, "button_sv", lambda *a: (1, 1))
    monkeypatch.setattr(shop, "cancel_visible", lambda *a: True)
    result = shop._buy(run, {"index": 2, "card_id": "card", "center": (126, 753)}, None,
                       confirm_reader=lambda _: pytest.fail("Jewel refusal must precede product approval"))
    assert not result.ok and "ジュエル" in result.error
    assert taps == [(126, 753), shop.EXCHANGE_TAP, shop.CANCEL_TAP]


def test_residual_recovery_confirmation_never_accepts_jewels():
    from hiro.produce.interval import _clear_recover_dialog
    taps = []
    boxes = [("体力回復確認", .99, (20, 20, 200, 50)), ("ジュエル", .99, (20, 70, 200, 100))]
    run = NS(shoot=lambda: object(), ocr=lambda _: boxes, snap=lambda *a: None, tap=taps.append)
    assert _clear_recover_dialog(run, accept=True) is False
    assert taps == [(220, 1160)]


def test_new_recovery_confirmation_cancels_jewels(monkeypatch):
    from hiro.produce import interval
    taps = []
    boxes = [("ジュエル", .99, (20, 70, 200, 100))]
    def until(done, timeout, tick=None):
        if tick:
            tick(object())
        return False, object()
    run = NS(shoot=lambda: object(), ocr=lambda _: boxes, snap=lambda *a: None,
             tap=taps.append, clock=lambda: 100, until=until,
             result=lambda ok, error=None, **k: NS(ok=ok, error=error))
    monkeypatch.setattr(interval, "read_hp", lambda *a: (17, 33))
    monkeypatch.setattr(interval.shop, "read_p", lambda *a: 100)
    result = interval._recover(run, {"available": True}, target_hp=19)
    assert not result.ok and "ジュエル" in result.error
    assert taps == [interval.RECOVER_TAP, (220, 1160)]
