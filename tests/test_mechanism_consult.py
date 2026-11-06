import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from hiro.brain import mechanism_consult as module
from hiro.brain.llm import MockLLM
from hiro.contracts import ActionKind, GameState
from hiro.contracts.game_state import PageState, Source
from hiro.state.catalog import Catalog


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_CONSULT", "1")
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE IdolCard(id TEXT,name TEXT); CREATE TABLE ProduceCard(id TEXT,upgradeCount INT,name TEXT,produceDescriptions TEXT); CREATE TABLE ProduceDrink(id TEXT,name TEXT,produceDescriptions TEXT);")
    db.execute("INSERT INTO IdolCard VALUES ('idol','Actual idol')")
    db.executemany("INSERT INTO ProduceCard VALUES (?,?,?,?)", [("card", n, "Card" + str(n), json.dumps([{"text": "Effect" + str(n)}])) for n in (0, 1)])
    db.execute("INSERT INTO ProduceDrink VALUES ('drink','Drink',?)", (json.dumps([{"text": "Draw two"}]),))
    monkeypatch.setattr(module, "catalog", lambda: Catalog(db))
    state = GameState(seq=13, page=PageState(name="CONSULT"), produce={"produce_point": 100, "drinks": [], "drink_capacity": 4},
                      page_fields={"complete": True, "produce_point": 100, "drinks": [], "drink_capacity": 4,
                                   "shelf": [{"index": 2, "kind": "card", "card_id": "card", "upgrade": 1, "price": 70, "purchased": False},
                                             {"index": 6, "kind": "drink", "drink_id": "drink", "price": 50, "purchased": False}]},
                      sources={"produce." + k: Source("screen", 13) for k in ("produce_point", "drinks", "drink_capacity")},
                      field_status={"produce." + k: "observed" for k in ("produce_point", "drinks", "drink_capacity")})
    yield state
    db.close()


def decider(reply):
    llm = MockLLM([reply])
    def ask(prompts, payload):
        result = llm.ask_json("test", json.dumps(payload))
        return result.data, [result.record()]
    return SimpleNamespace(llm=llm, _ask=ask)


def test_accurate_version_incomplete_deck_and_budget(setup):
    d = decider({"action": "buy", "index": 2, "reason": "mechanism"})
    result = module.compare(d, setup, "idol")
    assert result.action.kind is ActionKind.SHOP_BUY and result.action.args == {"index": 2}
    payload = json.loads(d.llm.calls[0][1])
    assert payload["candidates"][0]["upgrade"] == 1 and payload["candidates"][0]["master_effect_text"] == "Effect1"
    assert payload["deck"]["complete"] is False and payload["deck"]["absence_claim_allowed"] is False
    assert payload["held_drink_effects"] == []
    assert module.compare(d, setup, "idol").action.kind is ActionKind.SHOP_END
    unchanged = replace(setup, seq=14, sources={k: Source("screen", 14) for k in setup.sources})
    assert module.compare(d, unchanged, "idol").action.kind is ActionKind.SHOP_END
    # A fresh screen P reading reauthorizes spending only within the new budget.
    fresh = replace(setup, seq=14, produce={**setup.produce, "produce_point": 30},
                    page_fields={**setup.page_fields, "produce_point": 30},
                    sources={k: Source("screen", 14) for k in setup.sources})
    assert module.compare(d, fresh, "idol").action.kind is ActionKind.SHOP_END
    assert len(d.llm.calls) == 1


@pytest.mark.parametrize("origin,seq,status,pending", [("infer", 13, "observed", []), ("screen", 12, "observed", []),
    ("screen", 13, "pending", []), ("screen", 13, "observed", ["produce.produce_point"])])
def test_inferred_stale_or_pending_p_never_buys(setup, origin, seq, status, pending):
    setup.sources["produce.produce_point"] = Source(origin, seq)
    setup.field_status["produce.produce_point"] = status
    setup.pending_review = pending
    d = decider({"action": "buy", "index": 2, "reason": "x"})
    assert module.compare(d, setup, "idol").action.kind is ActionKind.SHOP_END
    assert d.llm.calls == []


@pytest.mark.parametrize("kind", ["full", "unknown", "stale"])
def test_drink_capacity_requires_current_verified_room(setup, kind):
    if kind == "full":
        setup.produce["drinks"] = setup.page_fields["drinks"] = ["drink"] * 4
    elif kind == "unknown":
        setup.produce["drink_capacity"] = setup.page_fields["drink_capacity"] = None
    else:
        setup.sources["produce.drinks"] = Source("screen", 12)
    payload = module.build_context(setup, "idol", module.catalog())
    assert [x["index"] for x in payload["candidates"]] == [2]


@pytest.mark.parametrize("reply", [{"action": "delete", "index": 2, "reason": "x"}, {"action": "buy", "index": True, "reason": "x"},
    {"action": "buy", "index": 99, "reason": "x"}, {"action": "buy", "index": 2, "reason": "x", "service": "upgrade"},
    {"action": "buy", "index": 2, "reason": ""}, RuntimeError("failed"), {"action": "end", "reason": "save P"}])
def test_whitelist_and_model_failure_end(setup, reply):
    assert module.compare(decider(reply), setup, "idol").action.kind is ActionKind.SHOP_END


def test_disabled_no_model_and_unknown_version_end(setup, monkeypatch):
    d = decider({"action": "buy", "index": 2, "reason": "x"})
    monkeypatch.delenv("HIRO_MECHANISM_CONSULT")
    assert module.compare(d, setup, "idol").action.kind is ActionKind.SHOP_END and not d.llm.calls
    monkeypatch.setenv("HIRO_MECHANISM_CONSULT", "1")
    assert module.compare(SimpleNamespace(llm=None), setup, "idol").action.kind is ActionKind.SHOP_END
    setup.page_fields["shelf"] = [{"index": 2, "kind": "card", "card_id": "card", "price": 10, "purchased": False}]
    assert module.compare(d, setup, "idol").action.kind is ActionKind.SHOP_END and not d.llm.calls


def test_legal_drink_purchase_has_complete_effect_and_original_index(setup):
    d = decider({"action": "buy", "index": 6, "reason": "draw supports current engine"})
    result = module.compare(d, setup, "idol")
    assert result.action.kind is ActionKind.SHOP_BUY and result.action.args == {"index": 6}
    payload = json.loads(d.llm.calls[0][1])
    assert payload["candidates"][1]["master_effect_text"] == "Draw two"


@pytest.mark.parametrize("patch", [{"price": None}, {"price": True}, {"price": -1}, {"price": 101},
                                    {"purchased": True}, {"upgrade": None}, {"customized": True}])
def test_unknown_unaffordable_or_unobserved_versions_are_excluded(setup, patch):
    setup.page_fields["shelf"] = [{**setup.page_fields["shelf"][0], **patch}]
    d = decider({"action": "buy", "index": 2, "reason": "x"})
    assert module.compare(d, setup, "idol").action.kind is ActionKind.SHOP_END
    assert not d.llm.calls
