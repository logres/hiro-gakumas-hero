import copy
from types import SimpleNamespace

import pytest

from hiro.brain.customization_context import transformation_context, semantic_context
from hiro.brain.mechanism_card_selection import build_context
from hiro.contracts import Event, GameState
from hiro.defaults.exam_state import hand_customization_context
from hiro.loop.events import apply_event, events_from_step


class Master:
    def card(self, cid, upgrade):
        return {"produceCardCustomizeIds": ["single", "multi"], "name": cid}

    def by_id(self, table, cid):
        return [{"customizeCount": i, "produceCardGrowEffectIds": [f"g{i}"],
                 "overwriteProduceCardGrowEffectType": "unknown"}
                for i in ([1] if cid == "single" else [1, 2])]

    def one(self, table, gid):
        return {"id": gid, "effectType": "synthetic_increment", "value": int(gid[1:])}


def event(cid="single", transaction="t"):
    action = {"kind": "CustomizeCard", "args": {"strict": True, "menu_session": True,
              "card_id": "a", "upgrade": 1, "levels": 1, "customize_id": cid}}
    proof = {"source": "strict_menu_settlement", "status": "confirmed",
             "final_click_sent": True, "transaction_id": transaction}
    return events_from_step("SPECIAL_GUIDANCE", action, True, {}, None, seq=8,
                            customization_evidence=proof)[0]


def apply(state, ev):
    return apply_event(state, ev, predictor=lambda *_: [])[0]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("HIRO_CUSTOMIZATION_TRANSFORM_CONTEXT", "1")


def test_success_evidence_deduplicates_but_never_claims_complete_history(enabled):
    state = GameState(produce={"deck": [{"card_id": "a", "upgrade": 1, "customized": True}]})
    state = apply(apply(state, event()), event())
    card = state.produce["deck"][0]
    assert len(card["customization_history"]) == 1
    context = transformation_context(card, Master())
    assert context["actual_effects_status"] == "unknown"
    assert context["history_completeness"] == "unknown"
    assert context["executed_customizations"][0]["count_status"] == "unique_master_candidate"


def test_multiple_levels_remain_candidates_despite_price_or_ocr(enabled):
    ev = event("multi")
    ev.args.update(price=40, customize_count=1, left=1)
    state = apply(GameState(produce={"deck": [{"card_id": "a", "upgrade": 1}]}), ev)
    context = transformation_context(state.produce["deck"][0], Master())
    item = context["executed_customizations"][0]
    assert item["count_status"] == "ambiguous_master_candidates"
    assert [c["customize_count"] for c in item["candidate_transformations"]] == [1, 2]


def test_missing_settlement_proof_and_duplicate_copy_do_not_bind(enabled):
    for copies, proof in [(1, {}), (2, event().args["execution_evidence"])]:
        ev = event(); ev.args["execution_evidence"] = proof
        state = apply(GameState(produce={"deck": [{"card_id": "a", "upgrade": 1}] * copies}), ev)
        assert all("customization_history" not in c for c in state.produce["deck"])


def test_review_unique_binding_and_version_change(enabled):
    state = apply(GameState(produce={"deck": [{"card_id": "a", "upgrade": 1}]}), event())
    review = Event(seq=9, kind="DECK_REVIEW", origin="review", confirmed=True,
                   args={"deck": [{"card_id": "a", "upgrade": 1, "customized": True}]})
    reviewed = apply(state, review)
    assert reviewed.produce["deck"][0]["customization_history"]
    review.args["deck"] *= 2
    assert all("customization_history" not in c for c in apply(state, review).produce["deck"])
    upgrade = Event(seq=10, kind="CARD_UPGRADE", origin="observed", args={"card_id": "a", "upgrade": 2})
    assert "customization_history" not in apply(reviewed, upgrade).produce["deck"][0]


def test_shared_owned_and_hand_context_and_provenance_semantics(enabled, monkeypatch):
    state = apply(GameState(produce={"deck": [{"card_id": "a", "upgrade": 1}]}), event())
    master = Master()
    monkeypatch.setattr("hiro.state.catalog.catalog", lambda: master)
    owned = build_context(state, {}, {}, master)["deck"]["observed_cards"][0]["customization_transformations"]
    hand = hand_customization_context([SimpleNamespace(card_id="a", upgrade=1, slot=0)], state.produce)
    assert hand["cards"][0]["customization_transformations"] == owned
    changed = copy.deepcopy(owned)
    changed["executed_customizations"][0].update(transaction_id="other", event_seq=99)
    assert semantic_context(changed) == semantic_context(owned)
    changed["executed_customizations"][0]["candidate_transformations"][0]["grow_effects"][0]["value"] = 2
    assert semantic_context(changed) != semantic_context(owned)


def test_default_off_and_incomplete_catalog_fail_closed(monkeypatch):
    monkeypatch.delenv("HIRO_CUSTOMIZATION_TRANSFORM_CONTEXT", raising=False)
    state = apply(GameState(produce={"deck": [{"card_id": "a", "upgrade": 1}]}), event())
    assert "customization_history" not in state.produce["deck"][0]
    class Broken(Master):
        def card(self, *_):
            return {"produceCardCustomizeIds": "single"}
    result = transformation_context({"card_id": "a", "upgrade": 1,
                                    "customization_history": [{"customize_id": "single"}]}, Broken())
    assert result["executed_customizations"][0]["candidate_transformations"] == []


def test_unknown_change_cannot_resurrect_old_binding(enabled):
    state = apply(GameState(produce={"deck": [{"card_id": "a", "upgrade": 1}]}), event())
    state = apply(state, Event(seq=9, kind="UNMODELED_CHANGE", origin="observed", args={"field": "deck"}))
    state = apply(state, Event(seq=10, kind="DECK_REVIEW", origin="review", confirmed=True,
                  args={"deck": [{"card_id": "a", "upgrade": 1, "customized": True}]}))
    assert "customization_history" not in state.produce["deck"][0]


def test_hand_unknown_inventory_and_identity_do_not_crash(enabled):
    assert hand_customization_context([SimpleNamespace(card_id=None, upgrade=None)], {"deck": None})["cards"] == []
    from hiro.brain.plan_evidence import effect_basis
    import json
    state = SimpleNamespace(hand=[SimpleNamespace(card_id=None, upgrade=None)],
        public_info="已验证主数据与本帧装备识别：" + json.dumps({"hand_customization": {"cards": [None,
            {"card_id": None, "upgrade": None, "customization_transformations": {"unknown": True}}]}}))
    assert effect_basis(state)["cards"] == {}
