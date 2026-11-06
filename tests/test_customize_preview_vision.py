"""Private frames are optional and never copied to fixtures."""
from pathlib import Path
import cv2
import numpy as np
import pytest
from hiro.vision import customize

pytestmark = pytest.mark.synthetic


def menu_boxes(columns=(0, 1)):
    boxes = [("カスタマイズメニュー", (250, 760, 470, 780)), ("合計あと1回", (430, 1010, 550, 1030))]
    for k in columns:
        x = 40 + 220 * k
        boxes += [("あと1回", (x, 790, x + 150, 810)), ("項目+", (x, 820, x + 160, 850)),
                  (str(70 + k * 30), (x + 60, 875, x + 120, 895))]
    return boxes


def test_missing_column_keeps_physical_index_and_unknown_ids(monkeypatch):
    from hiro.vision import deck, pages
    monkeypatch.setattr(deck, "card_from_name", lambda name: {"card_id": "card", "upgrade": 1})
    monkeypatch.setattr(pages, "read_hud_resources", lambda img: {})
    monkeypatch.setattr(customize, "master_offers", lambda *a: [{"id": "first"}, {"id": "second"}])
    boxes = menu_boxes((1, 2)) + [("カード+", (195, 173, 440, 199)), ("一覧に戻る", (100, 1070, 300, 1100))]
    img = np.zeros((1280, 720, 3), dtype=np.uint8)
    fields = customize.read_special_guidance(img, boxes)
    assert [it["item_index"] for it in fields["menu"]["items"]] == [1, 2]
    assert [it["id"] for it in fields["menu"]["items"]] == [None, None]
    fields = customize.read_special_guidance(img, menu_boxes() + boxes[-2:])
    assert [it["id"] for it in fields["menu"]["items"]] == ["first", "second"]


def test_tied_corner_evidence_is_unknown(monkeypatch):
    monkeypatch.setattr(customize, "_corner_px", lambda *a: 500)
    menu = customize.read_menu(np.zeros((1280, 720, 3), dtype=np.uint8), menu_boxes())
    assert menu["selected_item_index"] is None
    assert customize.read_preview(menu_boxes(), menu)["price"] is None


def test_raw_lines_preserve_missing_plus_and_upgrade():
    boxes = menu_boxes() + [("もう怖くないから", (195, 173, 440, 199)), ("好印象4", (290, 220, 390, 245)),
                            ("もう怖くないから＋", (195, 465, 440, 497)), ("開始時手札に入る", (195, 518, 550, 545))]
    menu = customize.read_menu(np.zeros((1280, 720, 3), dtype=np.uint8), boxes)
    preview = customize.read_preview(boxes, menu)
    assert preview["before"]["selected_card"]["upgrade"] is None
    assert preview["after"]["selected_card"]["upgrade"] == 1
    assert preview["before"]["effect_lines"] == [{"text": "好印象4", "box": [290, 220, 390, 245]}]
    assert preview["after"]["region"] == [20, 454, 700, 743]


@pytest.mark.parametrize(("name", "selected"), [("guidance-menu-before", None), ("guidance-preview-0", 0), ("guidance-preview-1", 1)])
def test_private_frame_corner_selection(name, selected):
    path = Path(__file__).parents[1] / "reports" / "windows-probe" / f"{name}.png"
    if not path.is_file():
        pytest.skip("private observed frame unavailable")
    menu = customize.read_menu(cv2.imread(str(path)), menu_boxes())
    assert menu["selected_item_index"] == selected
    assert customize.read_preview(menu_boxes(), menu)["price"] == {0: 70, 1: 100}.get(selected)
