from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from hiro.contracts import Action, ActionKind, Decision
from hiro.produce.customize_preview import MenuPreview
from hiro.produce.guidance_session import Hooks, run, result_reader


def decision(choice="wait"):
    return Decision(Action(ActionKind.WAIT, {"choice": choice}), choice, "test", None)


def menu():
    return {"view": "menu", "selected_card": {"card_id": "card", "upgrade": 1},
            "produce_point": 100, "cards_left": 1,
            "menu": {"total_left": 2, "selected_item_index": 0,
                     "items": [{"item_index": 0, "selected": True}]}}


class Session:
    def __init__(self):
        self.state = SimpleNamespace(page_fields={})
        self.observations, self.records = [], []

    def observe(self, **kwargs):
        self.observations.append(kwargs)
        self.state.page_fields = kwargs["fields"]
        return kwargs

    def record(self, obs=None, **kwargs):
        self.records.append(kwargs)


def setup():
    fields = menu()
    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    taps = []
    device = SimpleNamespace(screenshot=lambda: image, click=lambda *p: taps.append(p), swipe=lambda *p: None)
    read = lambda image: deepcopy(fields)
    hooks = Hooks(collect=lambda **kw: [MenuPreview(deepcopy(fields), image.copy())], ocr=lambda _: [])
    return fields, image, taps, device, read, hooks, Session()


def test_wait_keeps_menu_and_records_authoritative_images():
    fields, image, taps, device, read, hooks, session = setup()
    hooks.compare = lambda *args: decision()
    left = []
    with pytest.raises(ValueError, match="decision waits"):
        run(session, None, "idol", device=device, read=read, wait=lambda _: None,
            leave=lambda: left.append(True), hooks=hooks)
    assert not taps and not left
    assert session.observations[0]["fields"]["current_effects_observed"] is True
    assert session.observations[0]["fields"]["selected_card"]["customized"] is None
    assert session.observations[0]["img"].shape == image.shape
    assert session.records[-1]["decision"].action.kind == ActionKind.WAIT


def test_decline_returns_grid_and_excludes_reviewed_card():
    fields, _, taps, device, read, hooks, session = setup()
    hooks.compare = lambda *args: decision("decline")
    hooks.ocr = lambda image: [("一覧に戻る", (100, 1060, 300, 1100))]
    def click(*p):
        taps.append(p)
        fields.update(view="select", cards=[])
    device.click = click
    hooks.scan = lambda **kw: {"complete": True, "cards": [], "unknown_observations": []}
    def pick(*args, **kwargs):
        assert ("card", 1) in kwargs["reviewed"]
        assert ("card", 1) in kwargs["excluded"]
        return decision("decline")
    hooks.pick = pick
    left = []
    assert run(session, None, "idol", device=device, read=read, wait=lambda _: None,
               leave=lambda: left.append(True), hooks=hooks)
    assert taps == [(200, 1080)] and left == [True]


def test_success_recompares_actual_next_level_without_grid_navigation():
    fields, _, taps, device, read, hooks, session = setup()
    choices = []
    purchase = Decision(Action(ActionKind.CUSTOMIZE_CARD, {
        "card_id": "card", "upgrade": 1, "item_index": 0, "menu_session": True,
        "strict": True, "levels": 1, "price": 20, "customize_id": "offer"}), "buy", "test", None)
    def compare(decider, state, identity, reviews, jpeg):
        choices.append(deepcopy(reviews))
        assert jpeg.startswith(b"\xff\xd8")
        return purchase if len(choices) == 1 else decision()
    hooks.compare = compare
    hooks.prepare = lambda *args, **kw: SimpleNamespace(ok=True, taps=[], error=None)
    def commit(*args, **kwargs):
        fields["produce_point"] = 80
        fields["menu"]["total_left"] = 1
        return SimpleNamespace(ok=True, taps=[[500, 1160]], error=None)
    hooks.commit = commit
    hooks.scan = lambda **kw: pytest.fail("must preserve purchased menu")
    with pytest.raises(ValueError, match="decision waits"):
        run(session, None, "idol", device=device, read=read, wait=lambda _: None, hooks=hooks)
    assert len(choices) == 2
    assert choices[1][0]["produce_point"] == 80
    assert choices[1][0]["selected_card"]["customized"] is True
    assert any(r.get("execution") and r["execution"].ok for r in session.records)
    assert not taps


def test_step_cap_does_not_silently_leave():
    *_, device, read, hooks, session = setup()
    with pytest.raises(ValueError, match="step limit"):
        run(session, None, "idol", device=device, read=read, hooks=hooks, max_steps=0)


def test_wrapped_toast_uses_only_adjacent_bubble_text(monkeypatch):
    monkeypatch.setattr("hiro.vision.customize.read_customize_result",
                        lambda text: {"card_id": "card", "upgrade": 1})
    rows = [("カード+をカスタマイズしま", (100, 970, 620, 995)),
            ("した", (310, 1000, 360, 1025))]
    reader = result_reader(lambda _: {}, lambda _: rows)
    assert reader(None)["toast"]["center"] == [360, 997]
    rows[1] = ("した", (310, 1120, 360, 1145))
    assert "toast" not in reader(None)


def test_explicit_all_maxed_returns_grid_without_inferred_total():
    fields, _, taps, device, read, hooks, session = setup()
    fields["menu"]["total_left"] = None
    fields["menu"]["items"] = [{"item_index": 0, "id": "offer", "maxed": True}]
    hooks.collect = lambda **kwargs: pytest.fail("maxed menu cannot be previewed")
    hooks.ocr = lambda _: [("一覧に戻る", (100, 1060, 300, 1100))]
    def click(*p):
        fields.update(view="select", cards_left=0)
    device.click = click
    left = []
    assert run(session, None, "idol", device=device, read=read, wait=lambda _: None,
               leave=lambda: left.append(True), hooks=hooks)
    assert left == [True]


def test_failed_explicit_leave_stops():
    fields, _, _, device, read, hooks, session = setup()
    fields.update(view="select", cards_left=0)
    with pytest.raises(ValueError, match="exit was not verified"):
        run(session, None, "idol", device=device, read=read,
            leave=lambda: SimpleNamespace(ok=False), hooks=hooks)
