"""Customization evidence qualifies catalog text without changing frozen CardView schema."""

import json
from types import SimpleNamespace

from hiro.brain.cards import CardView
from hiro.brain.state import ExamMemory
from hiro.contracts import GameState
from hiro.defaults import exam_state


def card(slot=1, card_id="charm", upgrade=1):
    return CardView(slot, "charm+", card_id, upgrade, True, "mental", 4, 0, None, "好印象+5")


def test_exact_customized_version_qualifies_text_without_inventing_effects():
    hand = [card(), card(2, upgrade=0), card(3, card_id="other")]
    original = hand[0].to_dict()
    facts = exam_state.hand_customization_context(hand, {"deck": [
        {"card_id": "charm", "upgrade": 1, "customized": True,
         "customization_effects_known": True, "customize_id": "increase_to_6"}]})
    assert len(facts["cards"]) == 1
    entry = facts["cards"][0]
    assert (entry["slot"], entry["card_id"], entry["upgrade"]) == (1, "charm", 1)
    assert entry["customization_status"] == "customized"
    assert entry["effect_basis"] == "catalog_base_definition"
    assert entry["actual_effects_status"] == "unknown"
    assert entry["customization_effects_known"] is False
    assert "increase_to_6" not in json.dumps(facts)
    assert hand[0].to_dict() == original


def test_duplicate_copies_and_unknown_versions_do_not_claim_exact_customization():
    facts = exam_state.hand_customization_context([card()], {"deck": [
        {"card_id": "charm", "upgrade": 1, "customized": True},
        {"card_id": "charm", "upgrade": 1, "customized": False}]})
    assert facts["cards"][0]["customization_status"] == "ambiguous_owned_copies"
    for deck in ([], [{"card_id": "charm", "upgrade": None, "customized": True}],
                 [{"card_id": "charm", "upgrade": 0, "customized": True}]):
        assert exam_state.hand_customization_context([card()], {"deck": deck})["cards"] == []


def test_explicit_source_exposes_pending_deck_evidence_in_prompt(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setattr(exam_state, "screen_fields", lambda raw, session, img=None: raw)
    monkeypatch.setattr("hiro.brain.exam_context.verified_exam_context", lambda *a: {})
    source = exam_state.ScreenExamStateSource()
    session = SimpleNamespace(state=GameState(produce={"deck": [
        {"card_id": "charm", "upgrade": 1, "customized": True}]},
        field_status={"produce.deck": "pending"}), notes=[])
    source.begin({"session": session})
    frame = SimpleNamespace(raw={"hand": [card().to_dict()]}, img=None,
                            cards=[SimpleNamespace(card=None, available=True)], drinks=[],
                            remaining=12, hp=37, genki=0)
    state, _ = source.read(frame, ExamMemory("qualify-3"))
    payload = state.to_prompt_dict()
    facts = json.loads(payload["public_info"].split("已验证主数据与本帧装备识别：", 1)[1])
    assert facts["hand_customization"]["cards"][0]["actual_effects_status"] == "unknown"
    assert payload["hand"][0]["text"] == "好印象+5"
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE")
    state, _ = source.read(frame, ExamMemory("qualify-3"))
    assert state.public_info is None
