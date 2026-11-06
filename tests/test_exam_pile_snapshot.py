import numpy as np
from hiro.vision import exam_pile_snapshot as reader


def test_complete_draw_preserves_duplicates_and_incomplete_group_has_no_cards(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:[
        dict(pile="draw",count=2,box=[50,630,160,665]),dict(pile="grave",count=4,box=[50,847,160,880])])
    def grid(img,region,geometry):
        return [dict(card_id="same",name="same",upgrade=1,rect=(48+161*i,684,141,141)) for i in range(2)] if region[1]==665 else [dict(card_id="x",upgrade=0,rect=(48,899,141,141))]
    monkeypatch.setattr(reader.deck,"read_card_grid",grid)
    result=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))
    draw,grave=result["groups"]
    assert draw["complete"] and len(draw["cards"])==2
    assert all(c["observed_thumbnail_upgrade"]==1 and "upgrade" not in c for c in draw["cards"])
    assert not grave["complete"] and "cards" not in grave
    assert result["scope"]=="current_exam_groups" and result["draw_order"]=="unknown"


def test_unknown_identity_does_not_publish_partial_cards(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:[dict(pile="draw",count=1,box=[50,630,160,665])])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a:[dict(card_id=None,upgrade=None,rect=(48,684,141,141))])
    group=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))["groups"][0]
    assert not group["complete"] and "cards" not in group


def test_exact_heading_recovery_needs_two_scale_agreement(monkeypatch):
    def ocr(img,scale=3):
        if scale==3:return [("山札 ()",.9,(50,235,160,270))]
        return [("山札",.99,(0,5,80,40)),("(1)",.9,(80,5,140,40))]
    monkeypatch.setattr(reader,"ocr_boxes",ocr)
    assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"]==1
    monkeypatch.setattr(reader,"ocr_boxes",lambda img,scale=3: [("山札 ()",.9,(50,235,160,270))] if scale==3 else [("山札(1)" if scale==1 else "山札(2)",.9,(0,5,140,40))])
    assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"] is None

def test_duplicate_detection_rects_are_not_distinct_physical_copies(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:[dict(pile="draw",count=2,box=[50,630,160,665])])
    cell=dict(card_id="same",upgrade=1,rect=(48,684,141,141))
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a:[cell,dict(cell)])
    group=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))["groups"][0]
    assert not group["complete"] and "cards" not in group


def test_wrong_page_never_reads_groups(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:False)
    monkeypatch.setattr(reader,"_headings",lambda img: (_ for _ in ()).throw(AssertionError()))
    result=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))
    assert not result["active"] and result["groups"]==[]

def test_low_confidence_exact_count_is_not_trusted(monkeypatch):
    monkeypatch.setattr(reader,"ocr_boxes",lambda img,scale=3:[("山札(1)",.84,(50,235,160,270))])
    assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"] is None


def test_low_confidence_fallback_count_or_label_is_not_trusted(monkeypatch):
    for label_conf,count_conf in [(.99,.84),(.84,.99)]:
        def ocr(img,scale=3):
            return [("山札()",.99,(50,235,160,270))] if scale==3 else [("山札",label_conf,(0,5,80,40)),("(1)",count_conf,(80,5,140,40))]
        monkeypatch.setattr(reader,"ocr_boxes",ocr)
        assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"] is None


def test_duplicate_headings_do_not_publish_cards(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:[dict(pile="draw",count=1,box=[50,y,160,y+30]) for y in [420,630]])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a: (_ for _ in ()).throw(AssertionError()))
    result=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))
    assert all(not g["complete"] and "cards" not in g for g in result["groups"])


def test_unknown_or_negative_thumbnail_grade_is_incomplete(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:[dict(pile="draw",count=1,box=[50,630,160,665])])
    for grade in [None,-1,True]:
        monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a:[dict(card_id="card",upgrade=grade,rect=(48,684,141,141))])
        group=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))["groups"][0]
        assert not group["complete"] and "cards" not in group


def test_exact_zero_count_can_confirm_empty_visible_group(monkeypatch):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:[dict(pile="draw",count=0,box=[50,630,160,665])])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a:[])
    group=reader.read_exam_visible_groups(np.zeros((1280,720,3),np.uint8))["groups"][0]
    assert group["complete"] and group["cards"]==[]


def test_single_confident_scale_requires_independent_exact_token(monkeypatch):
    calls=[]
    def ocr(img,scale=3):
        if scale==3:return [("山札()",.99,(50,235,160,270))]
        return [("山札",.99,(0,5,80,40)),("（1)",.90 if scale==1 else .84,(80,5,140,40))]
    monkeypatch.setattr(reader,"ocr_boxes",ocr)
    monkeypatch.setattr(reader,"read_dddd",lambda img,box:calls.append(box) or 1)
    assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"]==1
    assert calls==[(105,623,165,658)]
    monkeypatch.setattr(reader,"read_dddd",lambda *a:2)
    assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"] is None


def test_explicit_ocr_conflict_never_uses_third_vote(monkeypatch):
    def ocr(img,scale=3):
        if scale==3:return [("山札()",.99,(50,235,160,270))]
        return [("山札",.99,(0,5,80,40)),("(1)" if scale==1 else "(2)",.99 if scale==1 else .84,(80,5,140,40))]
    monkeypatch.setattr(reader,"ocr_boxes",ocr)
    monkeypatch.setattr(reader,"read_dddd",lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"] is None


def test_missing_parenthesis_or_combined_label_never_gets_fixed_digit_crop(monkeypatch):
    for text in ["山札1)","山札(1)"]:
        def ocr(img,scale=3):
            if scale==3:return [("山札()",.99,(50,235,160,270))]
            return [(text,.99 if scale==1 else .84,(0,5,140,40))]
        monkeypatch.setattr(reader,"ocr_boxes",ocr)
        monkeypatch.setattr(reader,"read_dddd",lambda *a: (_ for _ in ()).throw(AssertionError()))
        assert reader._headings(np.zeros((1280,720,3),np.uint8))[0]["count"] is None
