"""Guidance entry uses destination evidence, including slow post-confirm transitions."""

import numpy as np
import pytest

import hiro  # noqa: F401
from hiro.produce import special_guidance as sg


def boxes(*texts):
    return [(text, 1.0, (350, 1040, 530, 1100)) for text in texts]


class Entry:
    def __init__(self, *, destination="grid", delay=0.0, missing=False, already=False, slow_ocr=False, tooltip=False):
        self.t = 0.0
        self.taps = []
        self.destination = destination
        self.delay, self.missing, self.already, self.slow_ocr = delay, missing, already, slow_ocr
        self.tooltip = tooltip

    def shoot(self):
        return np.zeros((2, 2, 3), dtype=np.uint8)

    def click(self, x, y):
        self.taps.append((x, y, self.t))

    def sleep(self, seconds):
        self.t += seconds

    def ocr(self, image):
        # As with real OCR, classify the captured frame before spending OCR time.
        entered = self.already or (len(self.taps) >= 2 and self.t - self.taps[1][2] >= self.delay)
        if self.slow_ocr:
            self.t += 3.0
        if entered:
            return boxes("カスタマイズ可能スキルカード") if self.destination == "grid" else boxes("カスタマイズメニュー", "一覧に戻る")
        if self.missing:
            return []
        source = boxes("特別指導")
        if self.tooltip and self.taps:
            source.append(("Pポイントを消費し、強化済みの", 1.0, (170, 800, 540, 840)))
        return source

    def run(self):
        return sg.enter(shoot=self.shoot, click=self.click, clock=lambda: self.t,
                        sleep=self.sleep, ocr=self.ocr, calib=False)


def test_missing_action_label_is_not_entry_success():
    flow = Entry(missing=True, delay=100)
    assert not flow.run().ok
    assert len(flow.taps) <= 2


@pytest.mark.parametrize("destination", ["grid", "menu"])
def test_already_in_guidance_does_not_tap_cards(destination):
    flow = Entry(already=True, destination=destination)
    assert flow.run().ok
    assert flow.taps == []


def test_two_phase_entry_waits_for_destination_after_confirmation():
    flow = Entry(delay=3.0)
    assert flow.run().ok
    assert len(flow.taps) == 2


def test_slow_ocr_checks_a_fresh_frame_after_confirmation():
    flow = Entry(delay=1.0, slow_ocr=True)
    assert flow.run().ok
    assert len(flow.taps) == 2


def test_stuck_selected_tooltip_fails_with_bounded_clicks():
    flow = Entry(delay=100, tooltip=True)
    assert not flow.run().ok
    assert len(flow.taps) == 2
    assert flow.t < 15


def test_selected_tooltip_triggers_confirmation_but_not_success():
    flow = Entry(tooltip=True, delay=1.0)
    assert flow.run().ok
    assert len(flow.taps) == 2
    assert 0.6 <= flow.taps[1][2] - flow.taps[0][2] < sg.ENTER_TIMEOUT / 2
