import copy
import json
from types import SimpleNamespace

import pytest

from hiro.brain import mechanism_customize as module
from hiro.brain.llm import MockLLM
from hiro.contracts import ActionKind, GameState


class Master:
    def one(self, table, identity):
        return {"id": identity, "name": identity, "examEffectType": "Review"}

    def card(self, identity, upgrade):
        return {"id": identity, "name": "Selected card", "category": "ProduceCardCategory_Mental",
                "produceDescriptions": [{"text": "base effect only"}],
                "produceCardCustomizeIds": ["opt0", "opt1", "opt2"]}


class ImageLLM(MockLLM):
    def ask_json(self, *args):
        raise AssertionError("text-only adapter must not be used")

    def ask_json_image(self, system, user, image_jpeg):
        self.image = image_jpeg
        return MockLLM.ask_json(self, system, user)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setenv("HIRO_MECHANISM_CUSTOMIZE", "1")
    monkeypatch.setattr(module, "catalog", Master)
    state = GameState(produce={"mode": "produce-007", "step": 19}, page_fields={"produce_point": 760})
    review = {"view": "menu", "produce_point": 760, "cards_left": 2,
              "selected_card": {"card_id": "a", "upgrade": 1, "customized": False},
              "menu": {"total_left": 2, "items": [
                  {"item_index": 2, "id": "opt2", "selected": True, "price": 40,
                   "available": True, "left": 2, "name": "effect increase"}]},
              "preview": {"selected_item_index": 2, "price": 40, "left": 2, "total_left": 2,
                          "before": {"effect_lines": ["partial OCR"]}, "after": {"effect_lines": []}}}
    return state, review


def reply(**changes):
    return {"action": "customize", "reason": "visible delta fits idol; costs 40P; further levels unreviewed",
            "card_id": "a", "card_name": "Selected card", "upgrade": 1, "item_index": 2, "price": 40, **changes}


def run(setup, answer=None, identity="idol-one"):
    llm = ImageLLM([reply() if answer is None else answer])
    result = module.compare_menu(SimpleNamespace(llm=llm), *setup[:1], identity, setup[1], b"current-jpeg")
    return result, llm


def test_image_adapter_shared_context_and_partial_ocr(setup):
    result, llm = run(setup)
    assert result.action.kind is ActionKind.CUSTOMIZE_CARD
    assert result.action.args == {"menu_session": True, "item_index": 2, "card_id": "a", "upgrade": 1,
                                  "price": 40, "levels": 1, "strict": True, "customize_id": "opt2"}
    assert llm.image == b"current-jpeg"
    payload = json.loads(llm.calls[0][1])
    assert payload["idol"]["id"] == "idol-one"
    assert payload["resources"]["produce_point"] == 760
    assert payload["customize_review"]["preview"]["after"]["effect_lines"] == []
    assert result.llm


def test_identity_not_route_table(setup):
    _, llm = run(setup, identity="idol-two")
    assert json.loads(llm.calls[0][1])["idol"]["id"] == "idol-two"


@pytest.mark.parametrize("changes", [{"item_index": True}, {"item_index": 0}, {"price": 41}, {"upgrade": 0},
    {"card_id": "other"}, {"card_name": "other"}, {"customize_id": "opt0"}, {"levels": 2},
    {"action": "end"}, {"reason": ""}])
def test_invalid_reply_never_authorizes_spending(setup, changes):
    result, _ = run(setup, reply(**changes))
    assert result.action.kind is ActionKind.WAIT
    assert result.action.args["choice"] == "wait"


def test_decline_and_failure_are_distinct_and_neither_ends(setup):
    declined, _ = run(setup, reply(action="decline"))
    uncertain, _ = run(setup, {"action": "wait", "reason": "after effect unreadable"})
    failed, _ = run(setup, RuntimeError("offline"))
    assert all(d.action.kind is ActionKind.WAIT for d in (declined, uncertain, failed))
    assert declined.action.args["choice"] == "decline"
    assert uncertain.action.args["choice"] == failed.action.args["choice"] == "wait"
    assert failed.llm


@pytest.mark.parametrize("path,value", [("selected_card.customized", None), ("selected_card.customized", True),
    ("selected_card.upgrade", None), ("produce_point", None), ("preview.price", 50),
    ("preview.selected_item_index", 0), ("menu.total_left", 0)])
def test_unknown_or_conflicting_review_skips_model(setup, path, value):
    state, review = setup
    target = review
    keys = path.split(".")
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    result, llm = run((state, review))
    assert result.action.kind is ActionKind.WAIT and not llm.calls


@pytest.mark.parametrize("changes", [{"available": None}, {"available": False}, {"left": 0},
                                    {"price": 800}, {"item_index": True}, {"id": "wrong"}])
def test_option_must_be_known_current_and_affordable(setup, changes):
    setup[1]["menu"]["items"][0].update(changes)
    result, llm = run(setup)
    assert result.action.kind is ActionKind.WAIT and not llm.calls


def test_duplicate_physical_indices_rejected(setup):
    setup[1]["menu"]["items"].append(copy.deepcopy(setup[1]["menu"]["items"][0]))
    assert not run(setup)[1].calls


def test_default_off_and_no_image(setup, monkeypatch):
    monkeypatch.delenv("HIRO_MECHANISM_CUSTOMIZE")
    assert not run(setup)[1].calls
    monkeypatch.setenv("HIRO_MECHANISM_CUSTOMIZE", "1")
    llm = ImageLLM([reply()])
    result = module.compare_menu(SimpleNamespace(llm=llm), setup[0], "idol", setup[1], b"")
    assert result.action.kind is ActionKind.WAIT and not llm.calls


def two_reviews(setup, *, other_price=70):
    first = copy.deepcopy(setup[1])
    first["menu"]["items"].append({"item_index": 0, "id": "opt0", "name": "other delta",
        "price": other_price, "left": 1, "available": True, "selected": False})
    second = copy.deepcopy(first)
    second["menu"]["items"][0]["selected"] = False
    second["menu"]["items"][1]["selected"] = True
    second["preview"].update(selected_item_index=0, price=other_price, left=1)
    return [first, second]


def run_options(setup, reviews, answer):
    llm = ImageLLM([answer])
    result = module.compare_options(SimpleNamespace(llm=llm), setup[0], "idol", reviews, b"side-by-side")
    return result, llm


def test_options_compares_mutually_exclusive_deltas_before_purchase(setup):
    result, llm = run_options(setup, two_reviews(setup), reply(item_index=0, price=70, customize_id="opt0"))
    assert result.action.kind is ActionKind.CUSTOMIZE_CARD
    assert result.action.args["item_index"] == 0 and result.action.args["levels"] == 1
    payload = json.loads(llm.calls[0][1])
    assert [o["item_index"] for o in payload["reviewed_options"]] == [2, 0]
    assert [o["image_panel_index"] for o in payload["reviewed_options"]] == [0, 1]
    assert llm.image == b"side-by-side"
    assert "current-card" in payload["session_opportunity_cost"]


@pytest.mark.parametrize("change", ["missing", "duplicate", "budget", "card", "levelcount", "optionprice", "availability"])
def test_options_requires_complete_unchanged_same_card_reviews(setup, change):
    reviews = two_reviews(setup)
    if change == "missing":
        reviews.pop()
    elif change == "duplicate":
        reviews[1] = copy.deepcopy(reviews[0])
    elif change == "budget":
        reviews[1]["produce_point"] -= 1
    elif change == "card":
        reviews[1]["selected_card"]["card_id"] = "other"
    elif change == "levelcount":
        reviews[1]["menu"]["total_left"] = 1
        reviews[1]["preview"]["total_left"] = 1
    elif change == "optionprice":
        reviews[1]["menu"]["items"][0]["price"] += 10
    else:
        for r in reviews:
            r["menu"]["items"].append({"item_index": 1, "available": None})
    result, llm = run_options(setup, reviews, reply())
    assert result.action.kind is ActionKind.WAIT and not llm.calls


def test_options_known_unaffordable_remains_visible_but_cannot_be_chosen(setup):
    reviews = two_reviews(setup, other_price=800)
    result, llm = run_options(setup, reviews, reply(item_index=0, price=800))
    assert result.action.kind is ActionKind.WAIT
    options = json.loads(llm.calls[0][1])["reviewed_options"]
    assert options[0]["affordable"] is True
    assert options[1]["affordable"] is False and options[1]["exclusion_reason"]


def test_options_reply_cannot_mix_one_option_index_and_other_price(setup):
    result, _ = run_options(setup, two_reviews(setup), reply(item_index=0, price=40))
    assert result.action.kind is ActionKind.WAIT


@pytest.mark.parametrize("action", ["decline", "wait"])
def test_options_decline_all_and_wait_do_not_end_guidance(setup, action):
    result, _ = run_options(setup, two_reviews(setup), {"action": action, "reason": "reviewed alternatives considered"})
    assert result.action.kind is ActionKind.WAIT
    assert result.action.args["choice"] == action


def test_customized_card_requires_current_image_effect_review(setup):
    state, review = setup
    review["selected_card"]["customized"] = True
    result, _ = run(setup)
    assert result.action.kind is ActionKind.WAIT
    review["current_effects_observed"] = True
    result, llm = run(setup)
    assert result.action.kind is ActionKind.CUSTOMIZE_CARD
    payload = json.loads(llm.calls[0][1])
    assert payload["customize_review"]["current_effects_observed"] is True
    assert "screenshot" in payload["effect_basis"]
