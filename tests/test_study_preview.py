from types import SimpleNamespace

import pytest

from hiro.produce.study_preview import collect


class Session:
    def __init__(self, selected=2, respond=True):
        self.selected, self.respond, self.seq = selected, respond, 0
        self.img = object()
        self.clicks, self.records = [], []

    def observe(self, **kw):
        self.seq += 1
        fields = kw.get("fields") or {
            "complete": True, "selected": self.selected, "effect": f"effect-{self.selected}",
            "choices": [dict(index=i, text=f"choice-{i}", center=[360, 698+100*i],
                             cost_hp=5, trouble=False) for i in range(3)]}
        return SimpleNamespace(fields=fields, seq=self.seq)

    def record(self, obs):
        self.records.append(obs)

    def click(self, x, y):
        index = (y-698)//100
        assert index != self.selected, "An already-selected choice would confirm it"
        self.clicks.append(index)
        if self.respond:
            self.selected = index


@pytest.mark.parametrize("selected", [0, 1, 2])
def test_collects_each_effect_without_confirming(selected):
    session = Session(selected)
    result = collect(session, session.observe(), session.click, lambda _: None)
    assert [c["effect"] for c in result.fields["choices"]] == [f"effect-{i}" for i in range(3)]
    assert all(c["preview_seq"] > 0 for c in result.fields["choices"])
    assert result.fields["selected"] == 2
    assert len(session.clicks) <= 3


def test_failed_single_click_stops_without_retry_or_confirm():
    session = Session(respond=False)
    with pytest.raises(ValueError, match="不补点"):
        collect(session, session.observe(), session.click, lambda _: None)
    assert session.clicks == [0]


def test_unknown_selection_prevents_any_click():
    session = Session(None)
    with pytest.raises(ValueError, match="选中态"):
        collect(session, session.observe(), session.click, lambda _: None)
    assert session.clicks == []


def test_four_line_effect_preserves_shifted_stat_line(monkeypatch):
    import cv2
    import numpy as np
    from hiro.vision import event

    img = np.zeros((1280, 720, 3), dtype=np.uint8)
    img[686:710, 120:520] = (140, 20, 240)
    assert cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[698, 200, 1] > 100

    def boxes(crop, **kw):
        if crop.shape[0] != event.REGION[3] - event.REGION[1]:
            return []
        return [("ボーカル上昇+150", 1, (7, 16, 240, 43)),
                ("トラブルカード以外", 1, (7, 57, 300, 86)),
                ("好印象関係のセレク", 1, (7, 100, 300, 129)),
                ("トチェンジ", 1, (7, 139, 240, 171))]
    monkeypatch.setattr(event, "ocr_boxes", boxes)
    fields = event.read_event_choices(img)
    assert fields["effect"].startswith("ボーカル上昇+150\n")
    assert "セレクトチェンジ" in fields["effect"].replace("\n", "")


def test_study_uses_verified_preview_not_title_or_day(monkeypatch):
    from hiro.brain import mechanism_change, route_guard
    from hiro.contracts import GameState, ActionKind

    monkeypatch.setattr(mechanism_change, "enabled", lambda: True)
    monkeypatch.setattr(mechanism_change, "readiness", lambda *args: True)
    monkeypatch.setattr(route_guard, "_idol_row", lambda _: {
        "examEffectType": "ProduceExamEffectType_ExamReview", "planType": "ProducePlanType_Plan2"})
    choices = [dict(index=i, text="ambiguous title", cost_hp=5, cost_p=None, trouble=False,
                    preview_seq=i+1, effect=effect) for i, effect in enumerate([
                        "好印象関係のセレク\nトチェンジ", "やる気関係のセレクトチェンジ"])]
    state = GameState(produce={"stamina": 39, "mode": "produce-007", "step": 17},
                      page_fields={"choices": choices})
    decider = SimpleNamespace(llm=object())
    result = route_guard._study(decider, state, "idol")
    assert result.action.kind == ActionKind.EVENT_SELECT
    assert result.action.args["select"] == 0
    monkeypatch.setattr(mechanism_change, "readiness", lambda *args: False)
    assert route_guard._study(decider, state, "idol").action.kind == ActionKind.WAIT
    monkeypatch.setattr(mechanism_change, "readiness", lambda *args: True)
    state.produce["stamina"] = 4
    assert route_guard._study(decider, state, "idol").action.kind == ActionKind.WAIT
    state.produce["stamina"] = 39
    choices[0]["trouble"] = True
    assert route_guard._study(decider, state, "idol").action.kind == ActionKind.WAIT
