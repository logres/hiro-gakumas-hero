import copy
import json
from types import SimpleNamespace

import pytest

from hiro.brain.card_effect_evidence import attach_card_effect_context, card_effect_context

pytestmark = pytest.mark.synthetic


HASH = "a" * 64
IDENTITY = {"slot": 0, "card_id": "any-idol-card", "upgrade": 1}


def record():
    return {**IDENTITY, "snapshot_sha256": HASH, "selection_verified": True,
            "selected_card": dict(IDENTITY), "detail_card": dict(IDENTITY),
            "raw_ocr_lines": ["好印象 +6", "体力消費"],
            "effects_known": True, "semantic_facts": [{"impression": 6}],
            "frame_path": "arbitrary.png"}


def context(records, hand=None, snapshot=HASH):
    return card_effect_context(hand or [SimpleNamespace(**IDENTITY)], records,
                               snapshot_sha256=snapshot)


def test_current_detail_preserves_raw_evidence_without_promoting_semantics():
    evidence = record()
    before = copy.deepcopy(evidence)
    facts = context([evidence])["cards"][0]
    assert facts["raw_ocr_lines"] == evidence["raw_ocr_lines"]
    assert facts["semantic_facts"] == []
    assert facts["ocr_completeness"] == "partial"
    assert facts["actual_effects_status"] == "unknown"
    assert facts["customization_effects_known"] is False
    assert "arbitrary.png" not in json.dumps(facts)
    facts["raw_ocr_lines"].append("mutation")
    assert evidence == before


@pytest.mark.parametrize("change", [
    {"slot": 1}, {"card_id": "other"}, {"upgrade": 0}, {"upgrade": True},
    {"snapshot_sha256": "b" * 64}, {"selection_verified": False},
    {"detail_card": {**IDENTITY, "upgrade": 0}},
    {"selected_card": {**IDENTITY, "slot": 1}},
    {"raw_ocr_lines": []}, {"raw_ocr_lines": [42]},
])
def test_mismatch_or_unreadable_evidence_is_omitted(change):
    assert context([{**record(), **change}])["cards"] == []


def test_duplicate_slots_and_same_version_other_slots_are_not_guessed():
    assert context([record(), record()])["cards"] == []
    assert context([record()], [SimpleNamespace(**IDENTITY), SimpleNamespace(**IDENTITY)])["cards"] == []
    second = SimpleNamespace(**{**IDENTITY, "slot": 1})
    assert context([record()], [SimpleNamespace(**IDENTITY), second])["cards"] == []


def test_optional_detail_image_hash_is_validated_and_preserved_for_audit():
    evidence = {**record(), "detail_sha256": "b" * 64}
    assert context([evidence])["cards"][0]["detail_sha256"] == "b" * 64
    assert context([{**evidence, "detail_sha256": "arbitrary.png"}])["cards"] == []


def test_optional_and_invalid_snapshot_do_not_change_public_info():
    hand = [SimpleNamespace(**IDENTITY)]
    assert attach_card_effect_context("catalog", hand, snapshot_sha256=HASH) == "catalog"
    assert context([record()], snapshot="path/to/frame.png")["cards"] == []
    result = attach_card_effect_context("catalog", hand, [record()], snapshot_sha256=HASH)
    assert result.startswith("catalog\n") and "好印象 +6" in result


def vision_record():
    return {**record(), "detail_sha256": "b"*64, "vision_transcription": {
        "status": "model_transcription_unverified", "lines": ["好印象+7"], "uncertain_spans": [],
        "provenance": {"identity": dict(IDENTITY), "snapshot_sha256": HASH,
            "detail_sha256": "b"*64, "encoded_image_sha256": "c"*64,
            "adapter": "mock", "model": "test-model", "prompt_version": "transcription@1.0"},
        "llmtrace": {"raw": "not public"}, "effects_known": True}}


def test_bound_vision_text_is_independent_and_json_reproducible():
    evidence = vision_record()
    first = context([evidence])
    frozen = json.loads(json.dumps(first, ensure_ascii=False))
    assert frozen == first == context([copy.deepcopy(evidence)])
    entry = first["cards"][0]
    assert entry["vision_transcription"]["lines"] == ["好印象+7"]
    assert entry["raw_ocr_lines"] == evidence["raw_ocr_lines"]
    assert entry["actual_effects_status"] == "unknown" and not entry["customization_effects_known"]
    assert "llmtrace" not in entry["vision_transcription"]
    assert "effects_known" not in entry["vision_transcription"]
    evidence["vision_transcription"]["lines"].append("mutated")
    evidence["vision_transcription"]["provenance"]["identity"]["slot"] = 9
    assert first == frozen


@pytest.mark.parametrize("change", [
    {"status": "verified"}, {"lines": []}, {"lines": [42]}, {"lines": ["x"*501]},
    {"uncertain_spans": "none"}, {"uncertain_spans": [""]},
])
def test_invalid_vision_content_keeps_raw_ocr(change):
    evidence = vision_record()
    evidence["vision_transcription"].update(change)
    entry = context([evidence])["cards"][0]
    assert "vision_transcription" not in entry and entry["raw_ocr_lines"]


@pytest.mark.parametrize("key,value", [
    ("identity", {**IDENTITY, "slot": 1}), ("snapshot_sha256", "d"*64),
    ("detail_sha256", "d"*64), ("encoded_image_sha256", "path"),
    ("adapter", ""), ("model", None), ("prompt_version", 1),
])
def test_invalid_vision_provenance_keeps_raw_ocr(key, value):
    evidence = vision_record()
    evidence["vision_transcription"]["provenance"][key] = value
    assert "vision_transcription" not in context([evidence])["cards"][0]


def test_vision_does_not_bypass_stale_duplicate_or_missing_detail_binding():
    evidence = vision_record()
    assert context([evidence], snapshot="d"*64)["cards"] == []
    assert context([evidence, copy.deepcopy(evidence)])["cards"] == []
    del evidence["detail_sha256"]
    assert "vision_transcription" not in context([evidence])["cards"][0]
