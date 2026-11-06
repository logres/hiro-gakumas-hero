"""Synthetic evidence only: never switches cards or clicks uncertain offers."""
import numpy as np
import pytest

from hiro.produce.idol_switch import BODY, TITLE, Step2Wait, decline_box, decline_offer


def offer(label="メ切り替えない"):
    return [(TITLE, .99, (140, 300, 580, 350)), (BODY, .99, (80, 400, 640, 450)),
            (label, .98, (100, 700, 330, 770)), ("切り替える", .99, (390, 700, 620, 770))]


@pytest.mark.parametrize("label", ["切り替えない", "メ切り替えない", "切り替え ない"])
def test_decline_only_observed_label(label):
    assert decline_box(offer(label)) == (100, 700, 330, 770)


def test_reject_missing_title_body_ambiguous_or_accept():
    rows = offer()
    for invalid in (rows[1:], rows[:1] + rows[2:], rows + [rows[2]], offer("切り替える")):
        assert decline_box(invalid) is None
    rows[2] = ("切り替えない", .7, rows[2][2])
    assert decline_box(rows) is None


def test_body_may_wrap_across_ocr_rows():
    # Retained textual evidence from DMM, without retaining its screenshot.
    rows = [(TITLE, .998, (62, 574, 439, 608)),
            ("新しく切り替え可能なプロデュースアイドルを入手して", .988, (53, 659, 649, 686)),
            ("います。", .988, (53, 689, 137, 716)),
            ("切り替えますか？", .999, (53, 718, 242, 744)),
            ("メ切り替えない", .979, (115, 1145, 327, 1175)),
            ("切り替える", .999, (451, 1142, 594, 1178))]
    assert decline_box(rows) == (115, 1145, 327, 1175)


def test_fresh_evidence_required_and_click_once():
    frame = np.zeros((1280, 720, 3), np.uint8)
    clicks = []
    assert decline_offer(shoot=lambda: frame.copy(), ocr=lambda _: offer(), click=lambda *p: clicks.append(p))
    assert clicks == [(215, 735)]
    clicks.clear()
    reads = iter([offer(), []])
    assert not decline_offer(shoot=lambda: frame.copy(), ocr=lambda _: next(reads), click=lambda *p: clicks.append(p))
    changed = frame.copy()
    changed[700:770, 100:330] = 255
    frames = iter([frame, changed])
    assert not decline_offer(shoot=lambda: next(frames), ocr=lambda _: offer(), click=lambda *p: clicks.append(p))
    assert not clicks


def test_wait_disabled_by_default_and_forwards_arguments(monkeypatch):
    monkeypatch.delenv("HIRO_DECLINE_IDOL_SWITCH", raising=False)

    class Original:
        def wait(self, *args, **kwargs):
            return args, kwargs

    assert Step2Wait(Original()).wait(timeout=3) == ((), {"timeout": 3})
