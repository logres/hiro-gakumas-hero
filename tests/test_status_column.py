"""Status-column holes must not erase later, currently observed effects."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from hiro.vision import status
from hiro.vision.observe import battle_observation


def read_synthetic(monkeypatch, scores, entries):
    inspected, read = [], []

    def score(img, slot):
        inspected.append(slot)
        return scores.get(slot, 0)

    def read_slot(img, slot):
        read.append(slot)
        return {"slot": slot, **entries[slot]}

    monkeypatch.setattr(status, "diamond_score", score)
    monkeypatch.setattr(status, "_read_slot", read_slot)
    monkeypatch.setattr(status, "_trailing_enchant", lambda *_: None)
    rows = status.read_status_column(np.zeros((1280, 720, 3), dtype=np.uint8))
    assert inspected == list(range(status.MAX_SLOTS))
    return rows, read


def observed(rows):
    return battle_observation({"statuses": rows, "status": status.status_summary(rows)})


def test_middle_low_outline_keeps_unknown_and_reads_later_current_value(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {0: 1, 1: .333, 2: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
        2: {"kind": "status", "key": "examcardplayaggressive", "value": 25},
    })
    assert read == [0, 2]
    assert rows[1]["uncertain"] == "slot_outline"
    assert [r["slot"] for r in rows] == [0, 1, 2]
    assert observed(rows)["motivation"] == 25


def test_middle_unknown_prevents_absence_becoming_zero(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1, 2: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
        2: {"kind": "enchant", "name": "known enchant", "value": None},
    })
    assert observed(rows)["motivation"] is None
    assert observed(rows)["impression"] == 161


def test_trailing_empty_slots_are_not_unknown_middle_slots(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {0: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
    })
    assert read == [0] and len(rows) == 1
    assert observed(rows)["motivation"] is None


def test_low_scoring_final_icon_cannot_turn_missing_status_into_zero(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {0: 1, 1: .333}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
    })
    assert read == [0]
    assert observed(rows)["motivation"] is None


def test_explicit_inactive_icon_still_confirms_zero(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1}, {
        0: {"kind": "status", "key": "examcardplayaggressive", "value": 0, "inactive": True},
    })
    assert observed(rows)["motivation"] == 0


def test_recognized_icon_with_unreadable_number_is_unknown(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1}, {
        0: {"kind": "status", "key": "examcardplayaggressive", "value": None},
    })
    assert observed(rows)["motivation"] is None


def test_unknown_blue_icon_keeps_absent_state_unknown(monkeypatch):
    rows, _ = read_synthetic(monkeypatch, {0: 1, 1: 1}, {
        0: {"kind": "status", "key": "examreview", "value": 161},
        1: {"kind": "status", "key": None, "value": 25},
    })
    assert observed(rows)["motivation"] is None


def test_empty_column_is_unknown(monkeypatch):
    rows, read = read_synthetic(monkeypatch, {}, {})
    assert rows == read == []
    assert observed(rows)["motivation"] is None


def test_unidentified_nonblue_slot_cannot_prove_status_absence():
    rows = [{"slot": 0, "kind": "status", "key": "examreview", "value": 161},
            {"slot": 1, "kind": "enchant", "card_id": None, "value": None}]
    assert observed(rows)["motivation"] is None


def test_sparse_external_column_does_not_claim_absence():
    rows = [{"slot": 0, "kind": "status", "key": "examreview", "value": 161},
            {"slot": 2, "kind": "enchant", "value": None}]
    assert observed(rows)["motivation"] is None


def test_initial_unknown_core_values_reach_model_without_stopping(monkeypatch):
    from hiro.brain.cards import CardView, parse_tags
    from hiro.brain.llm import MockLLM
    from hiro.brain.state import BattleState, ExamMemory, UNKNOWN
    from hiro.contracts import Action
    from hiro.defaults.advisor import RuleLLMAdvisor

    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    values = observed([])
    hand = CardView(0, "setup", "synthetic", 0, True, "mental", 0, 0, None,
                    "好印象+3", parse_tags("setup", "好印象+3"))
    current = BattleState("qualify-1", 1, 10, 30, 45, 0, [hand],
                          motivation=values["motivation"], impression=values["impression"])
    payload = current.to_prompt_dict()
    assert all(name in payload["unknown"] for name in ("motivation", "impression"))
    assert payload["motivation"] == payload["impression"] == UNKNOWN
    llm = MockLLM([{"action": "play:0", "reason": "visible setup"}])
    advisor = RuleLLMAdvisor(None, llm)
    result = advisor.decide(current, ExamMemory("qualify-1"), None,
                            [Action.from_legal(a) for a in current.legal_actions()])
    assert result.action.legal_key() == "play:0" and len(llm.calls) == 1


def test_local_r15_seq53_reads_visible_motivation_25(monkeypatch):
    # Local evidence stays in ignored traces; no screenshot is added to git.
    path = Path(__file__).resolve().parents[1] / "traces/windows-qualify-04-r15/frames/00053.jpg"
    if not path.exists():
        pytest.skip("local r15 evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND", "hiro.platforms.windows.ocr")
    image = cv2.imread(str(path))
    rows = status.read_status_column(image)
    assert len(rows) == 8
    assert rows[1]["uncertain"] == "slot_outline"
    assert observed(rows)["motivation"] == 25
    assert observed(rows)["impression"] == 161


@pytest.mark.parametrize("text,confidence,padded,expected", [
    ("10", .99, 10, 10), ("10", .99, 1, None), ("1p", .99, 1, None),
    ("10", .8, 10, None)])
def test_status_numeric_recovery_requires_independent_complete_number(monkeypatch, text, confidence, padded, expected):
    monkeypatch.setattr(status, "ocr", lambda img, **kw: [(text,confidence)])
    boxes = []
    monkeypatch.setattr(status, "read_dddd", lambda img,box: boxes.append(box) or padded)
    image = np.zeros((1280,720,3), np.uint8)
    assert status._verified_status_number(image,3) == expected
    if boxes:
        cy = status._slot_y(3)
        assert boxes == [(status.SLOT_X+10,cy,status.SLOT_X+62,cy+34)]


def test_failed_font_status_uses_verified_number_instead_of_tight_crop_guess(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setattr(status,"read_leading_int",lambda *args:(None,None))
    monkeypatch.setattr(status,"_verified_status_number",lambda *_:10)
    monkeypatch.setattr(status,"_unit_label",lambda *_:None)
    assert status._value(np.zeros((1280,720,3),np.uint8),3,"status") == (10,None)


@pytest.mark.parametrize("score,value,unit,accepted", [
    (.82,2,"ターン",True), (.79,2,"ターン",False),
    (.82,None,"ターン",False), (.82,2,None,False), (.82,0,"回",False)])
def test_trailing_slot_needs_high_card_match_and_explicit_positive_duration(monkeypatch,score,value,unit,accepted):
    from types import SimpleNamespace
    monkeypatch.setattr(status,"match_enchant_card",lambda *_:(score,"art"))
    monkeypatch.setattr(status,"_card_from_asset",lambda _:SimpleNamespace(_id="card",name="effect"))
    monkeypatch.setattr(status,"_permanent_enchant_proof",lambda _:None)
    monkeypatch.setattr(status,"_value",lambda *_:(value,unit))
    monkeypatch.setattr(status,"ocr_boxes",lambda *args,**kw:[(f"{value}{unit}",.99,(0,0,80,30))] if unit else [])
    entry=status._trailing_enchant(np.zeros((1280,720,3),np.uint8),7)
    assert bool(entry) is accepted
    if accepted:
        assert entry["value"]==2 and entry["occupancy_basis"]=="card_art_and_duration"


def test_trailing_recovery_stops_at_first_background_without_skipping(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setattr(status,"diamond_score",lambda img,k:1. if k==0 else .2)
    monkeypatch.setattr(status,"_read_slot",lambda img,k:{"slot":k,"kind":"status","key":"examreview","value":10})
    inspected=[]
    def trailing(img,k):
        inspected.append(k)
        return {"slot":k,"kind":"enchant","name":"known","value":2,"unit":"ターン"} if k==1 else None
    monkeypatch.setattr(status,"_trailing_enchant",trailing)
    rows=status.read_status_column(np.zeros((1280,720,3),np.uint8))
    assert [row["slot"] for row in rows]==[0,1] and inspected==[1,2]


def test_local_r24_lossless_recovers_visible_10_and_final_duration(monkeypatch):
    path=Path(__file__).resolve().parents[1]/"reports/runs/20261107-071534/frames/00008-exam_card_detail_state_changed.png"
    if not path.exists():
        pytest.skip("local lossless evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    rows=status.read_status_column(cv2.imread(str(path)),cache=None)
    assert observed(rows)["motivation"]==10
    assert observed(rows)["impression"]==109
    last=rows[-1]
    assert last["name"]=="夢色リップ" and last["value"]==2 and last["unit"]=="ターン"
    assert last["occupancy_basis"]=="card_art_and_duration"
    assert len(rows)==8


def test_native_status_flag_off_keeps_legacy_numeric_fallback(monkeypatch):
    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE",raising=False)
    monkeypatch.setattr(status,"read_leading_int",lambda *args:(None,None))
    monkeypatch.setattr(status,"read_dddd",lambda *_:1)
    monkeypatch.setattr(status,"_unit_label",lambda *_:None)
    monkeypatch.setattr(status,"_verified_status_number",lambda *_:pytest.fail("flag off"))
    assert status._value(np.zeros((1280,720,3),np.uint8),3,"status")== (1,None)


def test_native_status_flag_off_does_not_extend_column(monkeypatch):
    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE",raising=False)
    monkeypatch.setattr(status,"diamond_score",lambda img,k:1. if k==0 else .2)
    monkeypatch.setattr(status,"_read_slot",lambda img,k:{"slot":k,"kind":"status","key":"examreview","value":10})
    monkeypatch.setattr(status,"_trailing_enchant",lambda *_:pytest.fail("flag off"))
    assert len(status.read_status_column(np.zeros((1280,720,3),np.uint8)))==1


@pytest.mark.parametrize("native,padded,glyph,expected", [
    ("20％",209,20,20), ("20％",209,29,None), ("20",209,20,None),
    ("20％",20,None,20)])
def test_percent_digit_conflict_requires_literal_unit_and_independent_glyphs(monkeypatch,native,padded,glyph,expected):
    monkeypatch.setattr(status,"ocr",lambda *args,**kw:[(native,.99)])
    monkeypatch.setattr(status,"read_dddd",lambda *_:padded)
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:glyph)
    assert status._verified_status_number(np.zeros((1280,720,3),np.uint8),6)==expected


@pytest.mark.parametrize("pieces,expected", [
    ([("2ター",.98,(0,0,54,36)),("ン",.64,(41,0,81,34))],{(2,"ターン")}),
    ([("2ター",.98,(0,0,54,36)),("ン",.98,(41,40,81,74))],set()),
    ([("2タ",.98,(0,0,54,36)),("ン",.98,(41,0,81,34))],set()),
    ([("2ター",.98,(0,0,54,36)),("ン",.98,(141,0,181,34))],set())])
def test_duration_box_join_never_crosses_baseline_or_invents_missing_text(pieces,expected):
    assert status._duration_candidates(pieces)==expected


def test_local_r25_lossless_percent_and_split_duration(monkeypatch):
    path=Path(__file__).resolve().parents[1]/"reports/runs/20261107-072647/frames/00005-exam_card_detail_state_changed.png"
    if not path.exists():
        pytest.skip("local lossless evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    rows=status.read_status_column(cv2.imread(str(path)),cache=None)
    assert observed(rows)["motivation"]==7
    assert observed(rows)["impression"]==123
    assert status.status_summary(rows)["examlessonvaluemultiple"]==20
    assert rows[-1]["name"]=="夢色リップ" and rows[-1]["value"]==2
    assert rows[-1]["unit"]=="ターン" and len(rows)==8


@pytest.mark.parametrize("body,tail,expected",[(.98,.64,True),(.60,.99,False),(.99,.59,False),(.88,.88,False)])
def test_duration_fragments_require_reliable_body_and_minimum_tail(body,tail,expected):
    boxes=[("2ター",body,(0,0,54,36)),("ン",tail,(41,0,81,34))]
    assert bool(status._duration_candidates(boxes)) is expected


def test_complete_duration_preserves_original_confidence_requirement():
    assert status._duration_candidates([("2ターン",.899,(0,0,81,34))]) == set()


def test_unknown_internal_font_glyph_cannot_be_dropped_to_make_short_number():
    assert status._font_digit_sequence([(0,10,20,"2"),(12,10,20,None),(24,10,20,"0")]) is None
    assert status._font_digit_sequence([(0,10,20,"2"),(12,10,20,"0")]) == 20


@pytest.mark.parametrize("other_score,expected",[(.60,True),(.79,False)])
def test_blue_fallback_compares_different_base_ids_not_character_art(monkeypatch,other_score,expected):
    from types import SimpleNamespace
    monkeypatch.setattr(status,"_enchant_index",lambda:(["a-art1","a-art2","b-art"],np.array([[.85],[.84],[other_score]])))
    monkeypatch.setattr(status,"_slot",lambda *args:None)
    monkeypatch.setattr(status,"_inner",lambda _:None)
    monkeypatch.setattr(status,"_norm",lambda _:np.ones(1))
    monkeypatch.setattr(status,"_card_from_asset",lambda asset:SimpleNamespace(_id=asset[0],name="known"))
    monkeypatch.setattr(status,"_value",lambda *args:(None,None))
    result=status._high_confidence_enchant(np.zeros((1,1,3),np.uint8),2)
    assert bool(result) is expected
    if expected:
        assert result["card_id"]=="a" and result["margin"]==.25


@pytest.mark.parametrize("ratio,enabled,known",[(.079,True,True),(.089,True,True),(.089,False,False)])
def test_blue_color_threshold_does_not_hide_verified_art_with_flag(monkeypatch,ratio,enabled,known):
    from types import SimpleNamespace
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1" if enabled else "0")
    image=np.zeros((100,100,3),np.uint8)
    blue=cv2.cvtColor(np.uint8([[[100,255,255]]]),cv2.COLOR_HSV2BGR)[0,0]
    image.reshape(-1,3)[:round(ratio*10000)]=blue
    monkeypatch.setattr(status,"_slot",lambda *args:image)
    monkeypatch.setattr(status,"_icon_index",lambda:({},{}))
    monkeypatch.setattr(status,"match_status_icon",lambda *args:[(.53,"unknown"),(.50,"other")])
    monkeypatch.setattr(status,"match_enchant_card",lambda *args:(.85,"art"))
    monkeypatch.setattr(status,"_card_from_asset",lambda _:SimpleNamespace(_id="card",name="permanent"))
    monkeypatch.setattr(status,"_value",lambda *args:(None,None))
    monkeypatch.setattr(status,"_high_confidence_enchant",lambda *args:{"kind":"enchant","card_id":"card","name":"permanent"})
    result=status._read_slot(image,2)
    assert (result.get("card_id")=="card") is known


def test_local_r26_color_branch_keeps_permanent_card(monkeypatch):
    base=Path(__file__).resolve().parents[1]/"reports/runs/20261107-073727/frames"
    if not base.exists():
        pytest.skip("local lossless evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    for seq in (5,7,9):
        rows=status.read_status_column(cv2.imread(str(base/f"{seq:05d}-exam_card_detail_state_changed.png")),cache=None)
        assert rows[2]["card_id"]=="p_card-02-ido-3_019"
        assert rows[2]["name"]=="もう怖くないから"
        assert rows[2]["score"]>=.8


@pytest.mark.parametrize("glyph,padded,expected",[(166,166,166),(166,16,None),(None,166,None)])
def test_complete_glyph_and_independent_ocr_recover_when_native_text_is_corrupted(monkeypatch,glyph,padded,expected):
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:glyph)
    monkeypatch.setattr(status,"read_dddd",lambda *_:padded)
    monkeypatch.setattr(status,"ocr",lambda *args,**kw:[("øó",.5)])
    assert status._verified_status_number(np.zeros((1280,720,3),np.uint8),0)==expected


def test_local_r27_failed_restore_frames_have_recoverable_exact_state(monkeypatch):
    base=Path(__file__).resolve().parents[1]/"reports/runs/20261107-074410/frames"
    if not base.exists():
        pytest.skip("local lossless evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    for seq in (27,33):
        rows=status.read_status_column(cv2.imread(str(base/f"{seq:05d}-exam_card_detail_state_changed.png")),cache=None)
        values=observed(rows)
        assert values["impression"]==166
        assert status.status_summary(rows)["examlessonvaluemultiple"]==20
        assert values["buffs"]=={"もう怖くないから":None,"虹色ドリーマー":None,
                                "輝くキミへ":None,"パラメータ上昇量増加":20,"ファンシーチャーム":None}


@pytest.mark.parametrize("noise,removed", [
    ((47,0,90,56,None),True),
    ((60,18,20,49,None),False),
    ((60,7,96,60,None),False),
    ((60,1,20,40,None),False)])
def test_edge_noise_requires_multiple_digits_and_different_baseline(noise,removed):
    digits=[(24,19,34,48,"1"),(66,18,36,49,"6"),(110,18,36,49,"6")]
    filtered=status._exclude_edge_background(digits+[noise],(102,156))
    assert (noise not in filtered) is removed
    value=status._font_digit_sequence([(x,w,h,char) for x,y,w,h,char in filtered])
    assert value == (166 if removed else None)


def test_single_digit_does_not_establish_background_exclusion_baseline():
    glyphs=[(24,19,34,48,"1"),(47,0,90,56,None)]
    assert status._exclude_edge_background(glyphs,(102,156))==glyphs


def test_peripheral_icon_fragment_does_not_become_internal_unknown_digit():
    assert status._font_digit_sequence([(5,27,40,None),(24,34,48,"1"),(66,36,49,"6")])==16


def test_local_r28_edge_background_does_not_hide_complete_166(monkeypatch):
    base=Path(__file__).resolve().parents[1]/"reports/runs/20261107-075500/frames"
    if not base.exists():
        pytest.skip("local lossless evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    for seq in (5,7,9):
        image=cv2.imread(str(base/f"{seq:05d}-exam_card_detail_state_changed.png"))
        assert status._font_digits_without_ring(image,0)==166
        assert status._value(image,0,"status")[0]==166


def test_multiscale_reference_views_have_bounded_count_and_fixed_vector_size():
    image=np.random.default_rng(4).integers(0,256,(256,240,3),dtype=np.uint8)
    views=status._multiscale_card_templates(image)
    assert len(views)==9
    assert all(view.shape==(status.CARD_INNER**2,) and view.dtype==np.float32 for view in views)
    assert all(np.isclose(np.linalg.norm(view),1) for view in views)
    assert image.shape==(256,240,3)


@pytest.mark.parametrize("enabled",[True,False])
def test_multiscale_reference_selection_preserves_flag_off_legacy_index(monkeypatch,enabled):
    legacy,windows=object(),object()
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1" if enabled else "0")
    monkeypatch.setattr(status,"_card_index",lambda:legacy)
    monkeypatch.setattr(status,"_windows_card_index",lambda:windows)
    assert status._enchant_index() is (windows if enabled else legacy)


def test_local_r29_multiscale_reference_verifies_same_card_without_lowering_threshold(monkeypatch):
    path=Path(__file__).resolve().parents[1]/"reports/runs/20261107-080008/frames/00011-exam_card_detail_state_changed.png"
    if not path.exists():
        pytest.skip("local lossless evidence not present")
    image=cv2.imread(str(path))
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","0")
    old_score,old_asset=status.match_enchant_card(image,7)
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    score,asset=status.match_enchant_card(image,7)
    assert old_score<.8 and score>=.8
    assert status._card_from_asset(asset)._id==status._card_from_asset(old_asset)._id=="p_card-02-men-2_058"
    verified=status._high_confidence_enchant(image,7)
    assert verified["margin"]>=status.CAPTURED_MIN_MARGIN
    recovered=status._trailing_enchant(image,7)
    assert recovered["value"] is None
    assert recovered["permanent_proof"]["actual_duration_status"]=="unknown"
    assert recovered["permanent_proof"]["actual_customization_status"]=="unknown"


@pytest.mark.parametrize("turn,count,allowed",[(-1,0,True),(3,0,False),(-1,2,False),(None,0,False),(-1,None,False)])
def test_master_permanent_candidate_requires_explicit_unlimited_turn_and_count(turn,count,allowed):
    from types import SimpleNamespace as NS
    effect=NS(effect_type="ProduceExamEffectType_ExamStatusEnchant",effect_turn=turn,effect_count=count,
              _produce_exam_status_enchant_id="enchant",_id="source")
    variants=[NS(upgrade_count=i,play_effects=[NS(produce_exam_effect=effect)]) for i in range(4)]
    assert bool(status._permanent_enchant_signature(variants)) is allowed


def test_master_permanent_candidate_rejects_mixed_versions():
    from types import SimpleNamespace as NS
    def variant(grade,turn):
        return NS(upgrade_count=grade,play_effects=[NS(produce_exam_effect=NS(
            effect_type="ProduceExamEffectType_ExamStatusEnchant",effect_turn=turn,effect_count=0,
            _produce_exam_status_enchant_id="enchant",_id=f"source{grade}"))])
    assert status._permanent_enchant_signature([variant(0,-1),variant(1,3)]) is None


@pytest.mark.parametrize("proof,value,accepted",[(None,None,False),({"master_duration_basis":"candidate_only"},None,True),
                                                ({"master_duration_basis":"candidate_only"},4,False)])
def test_missing_duration_does_not_prove_permanence_or_overwrite_positive_value(monkeypatch,proof,value,accepted):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(status,"match_enchant_card",lambda *_:(.93,"art"))
    monkeypatch.setattr(status,"_card_from_asset",lambda _:NS(_id="card",name="source"))
    monkeypatch.setattr(status,"_permanent_enchant_proof",lambda _:proof)
    monkeypatch.setattr(status,"_high_confidence_enchant",lambda *_:{"card_id":"card","value":value})
    monkeypatch.setattr(status,"_value",lambda *_:(None,None))
    monkeypatch.setattr(status,"ocr_boxes",lambda *args,**kw:[])
    result=status._trailing_enchant(np.zeros((1280,720,3),np.uint8),7)
    assert bool(result) is accepted


def test_two_ocr_engines_cannot_overrule_conflicting_complete_digit_glyph(monkeypatch):
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:5)
    monkeypatch.setattr(status,"read_dddd",lambda *_:57)
    monkeypatch.setattr(status,"ocr",lambda *args,**kw:[("57",.99)])
    assert status._verified_status_number(np.zeros((1280,720,3),np.uint8),4) is None


@pytest.mark.parametrize("enabled,verified",[(True,True),(True,False),(False,True)])
def test_internal_outline_hole_requires_same_strict_art_evidence_as_trailing_slot(monkeypatch,enabled,verified):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1" if enabled else "0")
    monkeypatch.setattr(status,"diamond_score",lambda img,k:.8 if k==1 else (1. if k<3 else 0.))
    monkeypatch.setattr(status,"_read_slot",lambda img,k:{"slot":k,"kind":"status","key":"known","value":1})
    def evidence(img,k):
        return {"slot":k,"kind":"enchant","card_id":"source","value":None,"unit":None,
                "occupancy_basis":"card_art_and_master_permanent_candidate"} if k==1 and verified else None
    monkeypatch.setattr(status,"_trailing_enchant",evidence)
    rows=status.read_status_column(np.zeros((1280,720,3),np.uint8))
    assert (rows[1].get("card_id")=="source") is (enabled and verified)
    if not (enabled and verified):assert rows[1]["uncertain"]=="slot_outline"


def test_local_r30_pair_rejects_background_57_and_recovers_internal_fancy_only(monkeypatch):
    base=Path(__file__).resolve().parents[1]/"reports/runs/20261107-082327/frames"
    if not (base/"00085-exam_card_detail_state_changed.png").exists():
        pytest.skip("local lossless evidence not present")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    after=status.read_status_column(cv2.imread(str(base/"00085-exam_card_detail_state_changed.png")),cache=None)
    before=status.read_status_column(cv2.imread(str(base/"00086-exam_card_detail_baseline.png")),cache=None)
    assert observed(after)["motivation"] is None  # Correction, not a claimed recovery to 5.
    assert observed(before)["motivation"]==5
    assert after[2]["card_id"]==before[2]["card_id"]=="p_card-02-men-2_058"
    assert after[2]["value"] is None
    assert after[6]["name"]=="夢色リップ" and after[6]["value"]==3
    assert not any(row.get("name")=="夢色リップ" for row in before)  # Missing unit remains unsupported.


@pytest.mark.parametrize("boxes,glyph,expected",[
    ([("2",.99,(0,0,20,30)),("0％",.99,(18,0,58,30))],20,20),
    ([("2",.99,(0,0,20,30)),("0％",.99,(18,40,58,70))],20,None),
    ([("2",.99,(0,0,20,30)),("9％",.99,(18,0,58,30))],20,None),
    ([("2",.5,(0,0,20,30)),("0％",.99,(18,0,58,30))],20,None)])
def test_split_percent_requires_literal_same_baseline_text_and_independent_digits(monkeypatch,boxes,glyph,expected):
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:glyph)
    monkeypatch.setattr(status,"read_dddd",lambda *_:209)
    monkeypatch.setattr(status,"ocr",lambda *args,**kw:[(text,confidence) for text,confidence,_ in boxes])
    monkeypatch.setattr(status,"ocr_boxes",lambda *args,**kw:boxes)
    assert status._verified_status_number(np.zeros((1280,720,3),np.uint8),5)==expected


def test_local_r30_static_holdout_reads_current_values_and_both_card_sources(monkeypatch):
    folder=Path(__file__).resolve().parents[1]/"reports/windows-probe/r30-t5-static"
    paths=[folder/f"frame-{i}.png" for i in range(3)]
    if not all(path.exists() for path in paths):
        pytest.skip("private holdout evidence absent")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    for path in paths:
        rows=status.read_status_column(cv2.imread(str(path)),cache=None)
        values=status.status_summary(rows)
        assert values["examreview"]==43
        assert values["examcardplayaggressive"]==5
        assert values["examlessonvaluemultiple"]==20
        assert any(row.get("card_id")=="p_card-02-men-2_058" for row in rows)
        assert any(row.get("card_id")=="p_card-02-men-3_040" and row["value"]==3 for row in rows)


@pytest.mark.parametrize("scores,accepted",[( [.6339,.6311],False),([.7344,.7269],False),
                                          ([.9198,.4352],True)])
def test_ordinary_windows_enchant_rejects_close_wrong_winners(monkeypatch,scores,accepted):
    from types import SimpleNamespace as NS
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setattr(status,"_enchant_index",lambda:(["a","b"],np.array(scores).reshape(2,1)))
    monkeypatch.setattr(status,"_slot",lambda *a:np.zeros((56,56,3),np.uint8))
    monkeypatch.setattr(status,"_inner",lambda _:None)
    monkeypatch.setattr(status,"_norm",lambda _:np.ones(1))
    monkeypatch.setattr(status,"_card_from_asset",lambda asset:NS(_id=asset,name="candidate"))
    monkeypatch.setattr(status,"_icon_index",lambda:({},{}))
    monkeypatch.setattr(status,"match_status_icon",lambda *_:[(.1,"unknown"),(.05,"other")])
    monkeypatch.setattr(status,"_value",lambda *_:(None,None))
    row=status._read_slot(np.zeros((1280,720,3),np.uint8),6)
    assert (row.get("card_id")=="a") is accepted
    if not accepted:assert row["card_id"] is None and row["name"] is None


def test_enchant_unknown_font_cannot_publish_single_engine_background_one(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setattr(status,"read_leading_int",lambda *_:(None,None))
    monkeypatch.setattr(status,"_font_digits_without_ring",lambda *_:None)
    monkeypatch.setattr(status,"read_dddd",lambda *_:1)
    monkeypatch.setattr(status,"ocr",lambda *a,**kw:[])
    assert status._value(np.zeros((1280,720,3),np.uint8),7,"enchant","any-source")== (None,None)


def test_enchant_verified_font_positive_is_not_erased_by_master_permanence(monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    monkeypatch.setattr(status,"read_leading_int",lambda *_:(1,None))
    monkeypatch.setattr(status,"_verified_status_number",lambda *_:pytest.fail("already verified font"))
    assert status._value(np.zeros((1280,720,3),np.uint8),7,"enchant","any-source")== (1,None)


def test_enchant_flag_off_keeps_original_numeric_fallback(monkeypatch):
    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE",raising=False)
    monkeypatch.setattr(status,"read_leading_int",lambda *_:(None,None))
    monkeypatch.setattr(status,"read_dddd",lambda *_:1)
    monkeypatch.setattr(status,"_unit_label",lambda *_:None)
    monkeypatch.setattr(status,"_verified_status_number",lambda *_:pytest.fail("flag off"))
    assert status._value(np.zeros((1280,720,3),np.uint8),7,"enchant","any-source")== (1,None)


def test_local_r32_ambiguous_sources_rejected_reliable_dream_and_hikaru_retained(monkeypatch):
    base=Path(__file__).resolve().parents[1]/"reports/runs/20261107-090456/frames"
    if not (base/"00025-exam_card_detail_state_changed.png").exists():
        pytest.skip("private lossless evidence absent")
    monkeypatch.setenv("HIRO_OCR_BACKEND","hiro.platforms.windows.ocr")
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE","1")
    for seq,kind in [(25,"state_changed"),(26,"baseline"),(28,"state_changed"),(29,"baseline")]:
        image=cv2.imread(str(base/f"{seq:05d}-exam_card_detail_{kind}.png"))
        row=status._read_slot(image,6)
        if seq in (25,26):assert row.get("card_id") is None and row.get("name") is None
        else:assert row["card_id"]=="p_card-02-men-3_040" and row["value"]==1
        hikaru=status._read_slot(image,7)
        assert hikaru["card_id"]=="p_card-02-act-3_050" and hikaru["value"] is None
