import cv2
import numpy as np
import pytest
from hiro.vision import exam_card_details as reader


def setup(monkeypatch, headings=None):
    monkeypatch.setattr(reader.deck, "is_deck_list", lambda img: True)
    monkeypatch.setattr(reader, "_lines", lambda img, region: (
        [{"text": t, "confidence": .99, "box": box} for t, box in
         (headings if headings is not None else [("手札 (1)", [50,418,160,452]), ("山札 (2)", [50,630,160,670])])]
        if region == reader.deck.LIST_VIEW else []))
    cell = dict(index=0, row=0, col=0, rect=(48,469,141,141), card_id="card", name="name", upgrade=1)
    calls = []
    monkeypatch.setattr(reader.deck, "read_card_grid", lambda img, region, geometry: calls.append(region) or [cell])
    return calls


def test_hand_only_region(monkeypatch):
    calls = setup(monkeypatch)
    result = reader.read_exam_hand_details(np.zeros((1280,720,3), np.uint8))
    assert calls == [(0,452,720,630)]
    assert result["layout_complete"]
    assert result["identities_complete"]
    assert result["selected"] is None
    assert result["semantic_complete"] is False


def test_requires_next_pile(monkeypatch):
    calls = setup(monkeypatch, [("手札 (1)", [50,418,160,452])])
    result = reader.read_exam_hand_details(np.zeros((1280,720,3), np.uint8))
    assert not result["layout_complete"]
    assert calls == []


def test_cursor_four_corners_and_unique():
    img = np.zeros((1280,720,3), np.uint8)
    cards = [dict(index=0,rect=(48,469,141,141)), dict(index=1,rect=(209,469,141,141))]
    orange = cv2.cvtColor(np.uint8([[[15,255,255]]]), cv2.COLOR_HSV2BGR)[0,0]
    for x,y in ((32,453),(175,453),(32,596),(175,596)):
        img[y:y+30,x:x+30] = orange
    assert reader._selected(img, cards) == 0
    img[453:483,32:62] = 0
    assert reader._selected(img, cards) is None


def test_rejects_wrong_shape():
    assert not reader.read_exam_hand_details(np.zeros((10,10,3), np.uint8))["active"]

def test_mismatched_detail_not_attributed(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(reader, "_selected", lambda img,cards: 0)
    original = reader._lines
    monkeypatch.setattr(reader, "_lines", lambda img,region: [{"text":"other+", "confidence":.9,"box":[197,115,387,141]}] if region == reader.DETAIL_REGION else original(img,region))
    monkeypatch.setattr(reader.deck, "card_from_name", lambda text, ids: dict(card_id="other",name="other",upgrade=1))
    result = reader.read_exam_hand_details(np.zeros((1280,720,3),np.uint8))
    assert result["agree"] is False
    assert result["selected_card"] is None
    assert result["detail_lines"][0]["confidence"] == .9


def test_no_cursor_does_not_attribute_detail(monkeypatch):
    setup(monkeypatch)
    original = reader._lines
    monkeypatch.setattr(reader, "_lines", lambda img,region: [{"text":"name+", "confidence":.9,"box":[197,115,387,141]}] if region == reader.DETAIL_REGION else original(img,region))
    monkeypatch.setattr(reader.deck, "card_from_name", lambda text, ids: dict(card_id="card",name="name",upgrade=1))
    result = reader.read_exam_hand_details(np.zeros((1280,720,3),np.uint8))
    assert result["detail"] is not None
    assert result["selected_card"] is None


def test_layout_only_omits_effect_ocr_but_keeps_fresh_cards(monkeypatch):
    calls = setup(monkeypatch)
    original = reader._lines
    regions = []
    monkeypatch.setattr(reader, "_lines", lambda img, region:
                        regions.append(region) or original(img, region))
    result = reader.read_exam_hand_details(np.zeros((1280,720,3), np.uint8), include_detail=False)
    assert result["layout_complete"] and result["identities_complete"]
    assert result["detail_lines"] == [] and result["detail"] is None
    assert regions == [reader.deck.LIST_VIEW]
    assert calls == [(0,452,720,630)]


def test_active_template_match_needs_no_ocr(monkeypatch):
    monkeypatch.setattr(reader.deck, "is_deck_list", lambda _: True)
    monkeypatch.setattr(reader, "_lines", lambda *_: pytest.fail("unused OCR"))
    assert reader.is_exam_card_list(np.zeros((1280,720,3), np.uint8))


@pytest.mark.parametrize("title,tab,expected", [
    ("所持 スキルカード", True, True), ("所持スキルカード詳細", True, False),
    ("所持スキルカード", False, False)])
def test_active_exact_title_fallback_requires_active_tab(monkeypatch, title, tab, expected):
    monkeypatch.setattr(reader.deck, "is_deck_list", lambda _: False)
    monkeypatch.setattr(reader.deck, "_tab_active", lambda _: tab)
    monkeypatch.setattr(reader, "_lines", lambda *_: [{"text": title}])
    assert reader.is_exam_card_list(np.zeros((1280,720,3), np.uint8)) is expected


def title_index(monkeypatch, entries=None):
    monkeypatch.setattr(reader.deck, "card_from_name", lambda *_: None)
    monkeypatch.setattr(reader.deck, "_cards_by_full_name", lambda: entries or {
        "輝くキミへ+": [("card", 1)], "輝くキミへ+++": [("card", 3)]})


def test_detail_lookalike_preserves_exact_grade(monkeypatch):
    title_index(monkeypatch)
    assert reader._detail_from_name("輝くキミヘ+++", {"card"}, all_ids_known=True) == {
        "card_id":"card", "name":"輝くキミへ", "upgrade":3}
    assert reader._detail_from_name("輝くキミヘ+", {"card"}, all_ids_known=True)["upgrade"] == 1
    assert reader._detail_from_name("輝くキミヘ++", {"card"}, all_ids_known=True) is None


def test_detail_lookalike_rejects_ambiguous_normalized_titles(monkeypatch):
    title_index(monkeypatch, {"輝くキミへ+++": [("a",3)], "輝くキミヘ+++": [("b",3)]})
    assert reader._detail_from_name("輝くキミヘ+++", {"a","b"}, all_ids_known=True) is None


@pytest.mark.parametrize("text,ids,known", [
    ("輝くキミヘ+++", {"different"}, True),
    ("輝くキミヘ+++", {"card"}, False),
    ("輝くキミへ++ナ", {"card"}, True)])
def test_detail_lookalike_requires_known_candidate_and_no_other_edits(monkeypatch, text, ids, known):
    title_index(monkeypatch)
    assert reader._detail_from_name(text, ids, all_ids_known=known) is None


def test_detail_exact_name_lookup_takes_priority(monkeypatch):
    exact = {"card_id":"exact", "upgrade":3, "name":"name"}
    monkeypatch.setattr(reader.deck, "card_from_name", lambda *_: exact)
    monkeypatch.setattr(reader.deck, "_cards_by_full_name", lambda: pytest.fail("unneeded fallback"))
    assert reader._detail_from_name("name+++", {"exact"}, all_ids_known=True) is exact
