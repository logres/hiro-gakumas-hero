"""Synthetic formation navigation: no screenshots, OCR engines or game input."""

from types import SimpleNamespace as NS

import pytest

from hiro.loop import kaa_patches as patches


def navigate(values, target):
    reads, clicks, sleeps = iter(values), [], []
    patches._navigate_support_set(target, lambda: next(reads), clicks.append, sleeps.append)
    return clicks, sleeps


def test_seven_to_fifteen_verifies_every_single_step():
    clicks, _ = navigate(range(7, 16), 15)
    assert clicks == ["next"] * 8


def test_reverse_and_extreme_distance():
    assert navigate([7, 6, 5], 5)[0] == ["prev"] * 2
    assert len(navigate(range(1, 21), 20)[0]) == 19
    assert navigate([7], 7)[0] == []


@pytest.mark.parametrize("target", [0, 21, True, "7", None])
def test_invalid_target_never_reads_or_clicks(target):
    with pytest.raises(ValueError):
        patches._navigate_support_set(target, lambda: pytest.fail("read"), lambda _: pytest.fail("click"), lambda _: None)


@pytest.mark.parametrize("values", [[None] * 3, [7, 7, 7, 7], [7, 1], [7, 9], [7, None, None, None]])
def test_missing_stuck_or_unexpected_counter_stops(values):
    clicks, reads = [], iter(values)
    with pytest.raises(patches.SetSelectionPending):
        patches._navigate_support_set(15, lambda: next(reads), clicks.append, lambda _: None)
    assert len(clicks) <= 1


def test_animation_frames_are_read_without_extra_clicks():
    assert navigate([None, 7, 7, None, 8], 8)[0] == ["next"]


def test_step3_uses_same_verified_counter_not_original(monkeypatch):
    import kaa.tasks
    from hiro.vision import support_screens

    monkeypatch.setenv("HIRO_BOUNDED_SET_SELECTION", "1")
    monkeypatch.setattr(kaa.tasks, "R", NS(Produce=NS(
        TextStepIndicator2=NS(exists=lambda: False), TextStepIndicator3=NS(exists=lambda: True))))
    pages, clicks = iter([(1, 20), (2, 20), (3, 20)]), []
    monkeypatch.setattr(patches, "device", NS(screenshot=lambda: None, click=lambda *p: clicks.append(p)))
    monkeypatch.setattr(patches.time, "sleep", lambda _: None)
    monkeypatch.setattr(support_screens, "step2_page", lambda _: next(pages))
    patches._bounded_select_set(lambda _: pytest.fail("original fallback"))(3)
    assert clicks == [(700, 833), (700, 833)]


def test_flag_off_preserves_original_without_device(monkeypatch):
    monkeypatch.delenv("HIRO_BOUNDED_SET_SELECTION", raising=False)
    monkeypatch.setattr(patches, "device", NS(screenshot=lambda: pytest.fail("screenshot")))
    assert patches._bounded_select_set(lambda n: ("original", n))(15) == ("original", 15)


@pytest.mark.parametrize("step2,step3,expected", [(False, False, "unknown"), (False, True, "supported"), (True, False, "supported")])
def test_wrapper_screen_gate(monkeypatch, step2, step3, expected):
    import kaa.tasks
    from hiro.vision import support_screens

    monkeypatch.setenv("HIRO_BOUNDED_SET_SELECTION", "1")
    monkeypatch.setattr(kaa.tasks, "R", NS(Produce=NS(
        TextStepIndicator2=NS(exists=lambda: step2), TextStepIndicator3=NS(exists=lambda: step3))))
    clicks = []
    monkeypatch.setattr(patches, "device", NS(screenshot=lambda: None, click=lambda *p: clicks.append(p)))
    monkeypatch.setattr(support_screens, "step2_page", lambda _: (7, 20))
    fn = patches._bounded_select_set(lambda n: "original")
    if expected == "unknown":
        with pytest.raises(patches.SetSelectionPending):
            fn(7)
    else:
        assert fn(7) is None
    assert clicks == []


@pytest.mark.parametrize("step", [2, 3])
def test_screen_disappears_after_move_no_further_click(monkeypatch, step):
    import kaa.tasks
    from hiro.vision import support_screens

    monkeypatch.setenv("HIRO_BOUNDED_SET_SELECTION", "1")
    states = iter([True, True, False])
    indicator = NS(exists=lambda: next(states))
    monkeypatch.setattr(kaa.tasks, "R", NS(Produce=NS(
        TextStepIndicator2=indicator if step == 2 else NS(exists=lambda: False),
        TextStepIndicator3=indicator)))
    clicks = []
    monkeypatch.setattr(patches, "device", NS(screenshot=lambda: None, click=lambda *p: clicks.append(p)))
    monkeypatch.setattr(patches.time, "sleep", lambda _: None)
    monkeypatch.setattr(support_screens, "step2_page", lambda _: (7, 20))
    with pytest.raises(patches.SetSelectionPending):
        patches._bounded_select_set(lambda _: pytest.fail("fallback"))(15)
    assert clicks == [(700, 833)]


def test_selection_failure_uses_new_run_preparation_stop():
    assert issubclass(patches.SetSelectionPending, patches.FormationMismatch)

