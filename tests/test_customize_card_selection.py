from types import SimpleNamespace

import pytest

from hiro.brain import customize_card_selection as module
from hiro.contracts import ActionKind, GameState


class Master:
    def one(self, table, identity):
        return {"id": identity, "produceCardId": "signature"} if table == "IdolCard" else {"id": identity, "name": "offer", "price": 999}

    def card(self, identity, upgrade):
        return {"name": identity, "produceDescriptions": [{"text": "effect " + identity}],
                "produceCardCustomizeIds": ["offer"]}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(module, "enabled", lambda: True)
    state = GameState(produce={"deck": [], "deck_size": 0}, page_fields={
        "complete": True, "produce_point": 690, "cards_left": 1,
        "cards": [{"index": 3, "card_id": "a", "upgrade": 1, "available": True, "customized": False},
                  {"index": 5, "card_id": "b", "upgrade": 0, "available": True, "customized": True}]})
    return state


class Decider:
    llm = object()

    def __init__(self, reply=None):
        self.reply = reply or {"action": "review", "index": 3, "card_id": "a", "upgrade": 1, "reason": "inspect delta"}
        self.payload = None

    def _ask(self, prompts, payload):
        self.payload = payload
        assert prompts == ["customize_card_selection.md"]
        return self.reply, []


def run(state, decider=None, **kwargs):
    decider = decider or Decider()
    return module.select_card(decider, state, "idol-variant", master=Master(), **kwargs), decider


def test_review_never_authorizes_spending_and_preserves_context(setup):
    result, decider = run(setup)
    assert result.action.kind is ActionKind.CUSTOMIZE_CARD
    assert result.action.args == {"review_only": True, "card_id": "a", "upgrade": 1}
    p = decider.payload
    assert p["identity_mechanisms"]["signature_card"]["versions"][0]["master_effect_text"] == "effect signature"
    assert p["resources"]["produce_point"] == 690
    assert p["deck"]["complete"] is False
    assert p["candidates"][1]["customization_effects_unknown"] is True
    assert "price" not in p["candidates"][0]["master_customization_offers"][0]["definition"]


@pytest.mark.parametrize("field,value", [("complete", False), ("cards", None), ("produce_point", None), ("cards_left", None)])
def test_missing_inventory_skips_model(setup, field, value):
    setup.page_fields[field] = value
    result, decider = run(setup)
    assert result.action.kind is ActionKind.WAIT
    assert decider.payload is None


def test_unknown_active_card_and_duplicate_index_wait(setup):
    setup.page_fields["cards"][1]["index"] = 3
    assert run(setup)[1].payload is None
    setup.page_fields["cards"][1]["index"] = 5
    setup.page_fields["cards"][1]["upgrade"] = None
    assert run(setup)[1].payload is None


def test_exclusions_and_duplicate_ids_do_not_fallback_first(setup):
    result, decider = run(setup, reviewed={("a", 1)}, excluded={("b", 0)})
    assert result.action.args["choice"] == "decline"
    assert decider.payload is None
    setup.page_fields["cards"][1]["card_id"] = "a"
    assert run(setup)[0].action.args["choice"] == "decline"


@pytest.mark.parametrize("change", [{"index": 0}, {"upgrade": True}, {"price": 70}, {"action": "customize"}, {"card_id": "b"}])
def test_illegal_reply_waits(setup, change):
    decider = Decider()
    decider.reply.update(change)
    result, _ = run(setup, decider)
    assert result.action.kind is ActionKind.WAIT
    assert result.action.args["choice"] == "wait"
