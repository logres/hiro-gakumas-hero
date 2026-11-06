"""Synthetic memory picker frames and transition sequencing, without game input."""

from types import SimpleNamespace as NS

import numpy as np
import pytest

from hiro.vision import memory
from tools import memory_inventory as scan


PICKER = [("キャンセル", (100, 1140, 300, 1180)), ("決定", (490, 1140, 550, 1180)),
          ("所持メモリー", (130, 1020, 280, 1050))]


@pytest.mark.parametrize("text,expected", [("1 / 2", 1), ("2/2", 2), ("2 2", None), ("3/2", None), ("1/20", None)])
def test_fixed_pager_only_accepts_exact_fraction(monkeypatch, text, expected):
    from hiro.vision import ocr

    calls = []
    monkeypatch.setattr(ocr, "ocr", lambda im, **kw: calls.append((im.shape, kw)) or [(text, 1.0)])
    assert memory.fixed_detail_page(np.zeros((1280, 720, 3), np.uint8), PICKER) == expected
    assert calls == [((76, 124, 3), {"scale": 4, "languages": ("en-US",)})]


def test_fixed_pager_rejects_other_screen_before_ocr(monkeypatch):
    from hiro.vision import ocr

    monkeypatch.setattr(ocr, "ocr", lambda *a, **k: pytest.fail("OCR on wrong screen"))
    assert memory.fixed_detail_page(np.zeros((1280, 720, 3), np.uint8), [("2/2", (330, 520, 390, 550))]) is None


def test_verified_flag_does_not_fall_back_to_stale_content(monkeypatch):
    monkeypatch.setenv("HIRO_MEMORY_SCAN_VERIFIED", "1")
    monkeypatch.setattr(memory, "fixed_detail_page", lambda *a: None)
    boxes = [("獲得可能スキルカード", (0, 170, 300, 190))]
    assert memory.detail_page(boxes, np.zeros((1280, 720, 3), np.uint8)) is None
    monkeypatch.delenv("HIRO_MEMORY_SCAN_VERIFIED")
    assert memory.detail_page(boxes) == 1


def test_four_corners_reject_orange_art_and_covered_row():
    img = np.zeros((1280, 720, 3), np.uint8)
    orange = (0, 150, 255)
    # Neighbor's orange illustration should not beat an actual selected cell.
    img[590:700, 260:460] = orange
    for dx, dy in ((-109, -65), (109, -65), (-109, 65), (109, 65)):
        img[647 + dy - 9:647 + dy + 9, 140 + dx - 9:140 + dx + 9] = orange
    assert memory.verified_selected_cell(img) == (0, 0)
    img[560:735] = 0
    img[845:995] = orange
    assert memory.verified_selected_cell(img) is None


def test_wait_rejects_stale_cell_and_requires_stable_panel(monkeypatch):
    from hiro.vision import pages

    monkeypatch.setenv("HIRO_MEMORY_SCAN_VERIFIED", "1")
    # The next cell selection updates after the detail pager; do not accept it early.
    frames = iter([(0, "old"), (1, "loading"), (1, "new"), (1, "new")])
    monkeypatch.setattr(pages, "_texts", lambda im: PICKER + [(im[1], (100, 200, 300, 230))])
    monkeypatch.setattr(memory, "detail_page", lambda boxes, img: 1)
    monkeypatch.setattr(memory, "verified_selected_cell", lambda img: (0, img[0]))
    clock = [0.0]
    monkeypatch.setattr(scan.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scan.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    result = scan._wait_change(NS(screenshot=lambda: next(frames)), "old", 1, want_cell=(0, 1))
    assert result[0] == (1, "new") and result[3]
    assert clock[0] == pytest.approx(0.9)


def test_cold_ocr_still_allows_two_stability_observations(monkeypatch):
    from hiro.vision import pages

    monkeypatch.setenv("HIRO_MEMORY_SCAN_VERIFIED", "1")
    clock, reads = [0.0], [0]

    def boxes(img):
        reads[0] += 1
        clock[0] += 15 if reads[0] == 1 else 1
        return PICKER + [("stable", (100, 200, 300, 230))]

    monkeypatch.setattr(pages, "_texts", boxes)
    monkeypatch.setattr(memory, "detail_page", lambda boxes, img: 1)
    monkeypatch.setattr(scan.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scan.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    assert scan._wait_change(NS(screenshot=lambda: None), None, 1)[3]
    assert reads[0] == 2


@pytest.mark.parametrize("fail_at,clicks", [(1, []), (2, [(140, 647)]),
                                         (3, [(140, 647), scan.PAGER_NEXT]),
                                         (4, [(140, 647), scan.PAGER_NEXT, scan.PAGER_PREV])])
def test_transition_failure_stops_all_later_input(monkeypatch, tmp_path, fail_at, clicks):
    count, taps = [0], []

    def wait(*args, **kwargs):
        count[0] += 1
        return None, [], "panel", count[0] != fail_at

    monkeypatch.setattr(scan, "_wait_change", wait)
    monkeypatch.setattr(memory, "read_memory_detail", lambda *a: {})
    d = NS(click=lambda *p: taps.append(p), swipe=lambda *p: pytest.fail("swipe after failed transition"))
    with pytest.raises(scan.MemoryScanPending):
        scan._live_verified(d, 1, tmp_path)
    assert taps == clicks


def test_single_page_scan_never_taps_covered_row_or_swipes(monkeypatch, tmp_path):
    taps, cell = [], [None]

    def wait(d, prev, page, *, want_cell=None):
        if want_cell is not None:
            cell[0] = want_cell
        return np.zeros((1, 1, 3), np.uint8), [], str(cell[0]), True

    monkeypatch.setattr(scan, "_wait_change", wait)
    monkeypatch.setattr(memory, "read_memory_detail", lambda *a: {"card": {"card_id": str(cell[0])}})
    d = NS(click=lambda *p: taps.append(p), swipe=lambda *p: pytest.fail("swipe after requested last page"))
    assert len(scan._live_verified(d, 1, tmp_path)) == 6
    assert [p for p in taps if p[1] != 533] == [(x, y) for y in (647, 787) for x in (140, 360, 580)]
