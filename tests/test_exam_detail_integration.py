from types import SimpleNamespace

import numpy as np
import pytest

from hiro.exec import exam
from hiro.exec import card_detail_review as review
from hiro.loop.errors import ResumeBlocked


@pytest.mark.parametrize("restored", [True, False])
def test_detail_inspection_restoration_gates_decision_context(monkeypatch, restored):
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    identity = {"slot": 2, "card_id": "generic-card", "upgrade": 1}
    hand = [SimpleNamespace(**identity)]
    token = review.image_sha256(image)
    evidence = [{**identity, "selected_card": identity, "detail_card": identity,
                 "selection_verified": True, "snapshot_sha256": token,
                 "raw_ocr_lines": ["スキルカード使用数追加+1"]}]
    state = SimpleNamespace(hand=hand, public_info="catalog", legal_actions=lambda: ["play:2", "skip"])
    events = []
    rec = SimpleNamespace(log=lambda kind, **kwargs: events.append((kind, kwargs)))
    globals_ = exam._review_current_card_details.__globals__
    monkeypatch.setitem(globals_, "_detail_state_facts", lambda img: {"hp": 20})
    monkeypatch.setitem(globals_, "device", SimpleNamespace(screenshot=lambda: image, click=lambda p: None))
    monkeypatch.setattr(review, "review_exam_hand_details", lambda *a, **kw:
                        review.ReviewResult(evidence, image, [], restored))
    if not restored:
        with pytest.raises(ResumeBlocked, match="no battle input"):
            exam._review_current_card_details(state, SimpleNamespace(img=image), rec)
        assert state.public_info == "catalog"
    else:
        assert exam._review_current_card_details(state, SimpleNamespace(img=image), rec) is True
        assert "スキルカード使用数追加+1" in state.public_info
        assert token in state.public_info
    assert events[-1][1]["restored"] is restored


def test_detail_inspection_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HIRO_EXAM_CARD_DETAILS", raising=False)
    assert exam._review_current_card_details(None, None, None) is True


def test_changed_initial_facts_request_reobservation_without_context(monkeypatch):
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    state = SimpleNamespace(hand=[], public_info="catalog", legal_actions=lambda: ["drink:0", "skip"])
    events = []
    rec = SimpleNamespace(log=lambda kind, **kwargs: events.append((kind, kwargs)))
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "_detail_state_facts",
                        lambda _: {"hp": 20})
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "device",
                        SimpleNamespace(screenshot=lambda: image, click=lambda _: None))
    monkeypatch.setattr(review, "review_exam_hand_details", lambda *a, **kw:
                        review.ReviewResult([], image, ["initial_state_unverified"], False))
    assert exam._review_current_card_details(state, SimpleNamespace(img=image), rec) is False
    assert state.public_info == "catalog"
    assert events[-1][1]["problems"] == ["initial_state_unverified"]


def test_supervisor_does_not_restart_blocked_detail_inspection(monkeypatch):
    from hiro import run_hif
    from hiro.loop import resume

    attempts, recoveries = [], []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise ResumeBlocked("Card detail inspection did not restore the original exam")

    monkeypatch.setattr(resume, "run", blocked)
    session = SimpleNamespace(recover=lambda *args: recoveries.append(args))
    with pytest.raises(ResumeBlocked, match="Card detail inspection"):
        run_hif._supervised_resume(None, None, session, Strategy=object())
    assert attempts == [True]
    assert recoveries == []


def test_forced_skip_does_not_open_details(monkeypatch):
    from hiro.brain.cards import CardView
    from hiro.brain.state import BattleState
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    card = CardView(0, "unavailable", "any-card", 0, False, "mental", 0, 0, None, "")
    state = BattleState("qualify-3", 9, 4, 26, 45, 7, [card])
    assert state.legal_actions() == ["skip"]
    assert exam._review_current_card_details(state, None, None) is True
