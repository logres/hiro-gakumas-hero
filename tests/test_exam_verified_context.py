"""Exact equipment vs ambiguous icons, with no inferred idol or upgrade state."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from hiro.brain import exam_context
from hiro.brain.state import ExamMemory
from hiro.contracts import GameState
from hiro.defaults import exam_state
from hiro.state.catalog import Catalog, CatalogUnavailable


@pytest.fixture
def master(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE IdolCard (id TEXT, name TEXT, characterId TEXT, planType TEXT, examEffectType TEXT,
                               beforeProduceItemId TEXT, afterProduceItemId TEXT);
        CREATE TABLE Character (id TEXT, lastName TEXT, firstName TEXT);
        CREATE TABLE ProduceItem (id TEXT, name TEXT, assetId TEXT, produceDescriptions TEXT);
    """)
    db.executemany("INSERT INTO IdolCard VALUES (?,?,?,?,?,?,?)", [
        ("liliya", "白線", "kllj", "Plan2", "ExamReview", "log0", "log1"),
        ("hiro", "Campus", "shro", "Plan2", "ExamCardPlayAggressive", "hiro-item", "hiro-item-plus"),
    ])
    db.executemany("INSERT INTO Character VALUES (?,?,?)", [("kllj", "葛城", "リーリヤ"), ("shro", "篠澤", "広")])
    db.executemany("INSERT INTO ProduceItem VALUES (?,?,?,?)", [
        ("log0", "夢へのライフログ", "shared-icon", json.dumps([{"text": "ターン終了時、元気が7以上の場合、好印象+1"}])),
        ("log1", "夢へのライフログ+", "shared-icon", json.dumps([{"text": "ターン終了時、元気が7以上の場合、好印象+2"}])),
    ])
    monkeypatch.setattr(exam_context, "catalog", lambda: Catalog(db))
    yield
    db.close()


def test_identity_candidates_do_not_claim_equipment_or_other_idol(master):
    facts = exam_context.verified_exam_context("liliya", [])
    assert facts["identity"]["character_name"] == "葛城リーリヤ"
    assert facts["observed_pitems"] == []
    prior = facts["catalog_identity_item_variants"]
    assert prior["status"] == "expected_from_identity/not_observed"
    assert prior["actual_upgrade_status"] == "unknown"
    assert [it["item_id"] for it in prior["variants"]] == ["log0", "log1"]
    other = exam_context.verified_exam_context("hiro", [])
    assert other["identity"]["character_name"] == "篠澤広"
    assert "リーリヤ" not in json.dumps(other, ensure_ascii=False)
    assert exam_context.verified_exam_context(None, [])["identity"] == {"status": "unknown"}


def test_exact_item_id_supplies_only_observed_variant(master):
    facts = exam_context.verified_exam_context("liliya", [{"slot": 0, "item_id": "log0", "asset": "shared-icon"}])
    item = facts["observed_pitems"][0]
    assert item["variant_status"] == "confirmed_id"
    assert item["name"] == "夢へのライフログ"
    assert "好印象+1" in item["effect_text"]
    assert "candidate_variants" not in item and "log1" not in json.dumps(item)


def test_asset_keeps_actual_variants_as_alternatives(master):
    item = exam_context.verified_exam_context("liliya", [{"asset": "shared-icon"}])["observed_pitems"][0]
    assert item["variant_status"] == "unknown" and "effect_text" not in item
    assert [x["item_id"] for x in item["candidate_variants"]] == ["log0", "log1"]
    assert [x["effect_text"][-5:] for x in item["candidate_variants"]] == ["好印象+1", "好印象+2"]


def test_unrecognized_exact_id_does_not_fall_back_to_icon(master):
    item = exam_context.verified_exam_context("liliya", [{"item_id": "absent", "asset": "shared-icon"}])["observed_pitems"][0]
    assert item["variant_status"] == "unknown" and "candidate_variants" not in item


def test_missing_master_stays_unknown(monkeypatch):
    def unavailable():
        raise CatalogUnavailable("not installed")
    monkeypatch.setattr(exam_context, "catalog", unavailable)
    facts = exam_context.verified_exam_context("liliya", [{"item_id": "log0"}])
    assert facts["identity"]["status"] == "unknown"
    assert facts["master_data"] == "unavailable"
    assert "effect_text" not in json.dumps(facts)


def test_source_attaches_real_item_text_to_llm_payload_and_resets_identity(master, monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setattr(exam_state, "screen_fields", lambda raw, session, img=None: raw)
    source = exam_state.ScreenExamStateSource()
    source.begin({"idol_card_id": "liliya", "exam": "qualify-1"})
    frame = SimpleNamespace(raw={"pitems": [{"item_id": "log0"}]}, img=None,
                            cards=[], drinks=[], remaining=5, hp=20, genki=7)
    state, _ = source.read(frame, ExamMemory("qualify-1"))
    public = state.to_prompt_dict()["public_info"]
    assert "夢へのライフログ" in public and "好印象+1" in public and "葛城リーリヤ" in public
    source.begin({"exam": "qualify-2"})
    frame.raw = {"pitems": []}
    state, _ = source.read(frame, ExamMemory("qualify-2"))
    assert "リーリヤ" not in state.public_info and '"status": "unknown"' in state.public_info


def test_session_identity_wins_and_flag_off_preserves_payload(master, monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setattr(exam_state, "screen_fields", lambda raw, session, img=None: raw)
    session = SimpleNamespace(state=GameState(produce={"idol_card_id": "hiro"}), notes=[])
    source = exam_state.ScreenExamStateSource()
    source.begin({"idol_card_id": "liliya", "session": session})
    frame = SimpleNamespace(raw={"pitems": []}, img=None, cards=[], drinks=[], remaining=5, hp=20, genki=7)
    state, _ = source.read(frame, ExamMemory("qualify-1"))
    assert "篠澤広" in state.public_info and "リーリヤ" not in state.public_info
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE")
    state, _ = source.read(frame, ExamMemory("qualify-1"))
    assert state.public_info is None


@pytest.mark.parametrize("items,status", [
    ([{"item_id": "log0"}], "confirmed_id"),
    ([{"asset": "shared-icon"}], "unknown"),
    ([{"item_id": "absent"}], "unknown"),
])
def test_profile_does_not_hide_current_equipment_evidence(master, monkeypatch, items, status):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    monkeypatch.setattr(exam_state, "screen_fields", lambda raw, session, img=None: raw)
    monkeypatch.setattr(exam_state, "screen_state", lambda *a, **kw:
                        SimpleNamespace(public_info="profile reference", recommended_effect=None))
    source = exam_state.ScreenExamStateSource()
    source.begin({"idol_card_id": "liliya", "profile": SimpleNamespace(idol_id="hiro")})
    state, _ = source.read(SimpleNamespace(raw={"pitems": items}, img=None), ExamMemory("qualify-1"))
    assert state.public_info.startswith("profile reference\n")
    facts = json.loads(state.public_info.split("已验证主数据与本帧装备识别：", 1)[1])
    assert facts["identity"]["character_name"] == "葛城リーリヤ"
    assert facts["observed_pitems"][0]["variant_status"] == status
    if items[0].get("item_id") == "log0":
        assert "好印象+1" in facts["observed_pitems"][0]["effect_text"]
    else:
        assert "effect_text" not in facts["observed_pitems"][0]

def test_visible_count_preserved_without_resolving_shared_icon_variant(master):
    observed = {"slot":1,"asset":"shared-icon","rect":[634,313,66,66],
                "charges_box":[683,298,715,326],"remaining_charges":2,"charges_source":"visible_badge"}
    result=exam_context.verified_exam_context(None,[observed])["observed_pitems"][0]
    assert result["remaining_charges"] == 2
    assert result["charges_box"] == observed["charges_box"]
    assert result["variant_status"] == "unknown"
    assert len(result["candidate_variants"]) == 2
