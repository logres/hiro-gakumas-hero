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
    monkeypatch.setitem(globals_, "_detail_state_facts", lambda img, **kw: {"hp": 20})
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


def test_incomplete_baseline_reobserves_without_opening_or_deciding(monkeypatch):
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    state = SimpleNamespace(hand=[], public_info="catalog", legal_actions=lambda: ["drink:0", "skip"])
    events = []
    rec = SimpleNamespace(log=lambda kind, **kwargs: events.append((kind, kwargs)))
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "_detail_state_facts", lambda _, **kw: None)
    monkeypatch.setattr(review, "review_exam_hand_details", lambda *a, **kw: pytest.fail("must not open details"))
    assert exam._review_current_card_details(state, SimpleNamespace(img=np.zeros((2,2,3), dtype=np.uint8)), rec) is False
    assert state.public_info == "catalog"
    assert events[-1][1]["reason"] == "initial_state_unverified"
    assert events[-1][1]["lossless"] is True
    assert events[-1][1]["pixel_sha256"] == review.image_sha256(events[-1][1]["image"])


@pytest.mark.parametrize("attr,multiplier,complete", [("visual", None, False), (None, 2868, False), ("visual", 2868, True)])
def test_detail_baseline_requires_current_attribute_and_multiplier(monkeypatch, attr, multiplier, complete):
    from hiro.vision import hif, observe
    monkeypatch.setattr(hif, "is_hif_exam", lambda _: True)
    monkeypatch.setattr(hif, "read_hif_exam", lambda *a, **kw: {"attr": attr, "multiplier_pct": multiplier})
    monkeypatch.setattr(observe, "battle_observation", lambda _: {"remaining_turns": 12, "hp": 20, "genki": 0})
    facts = exam._detail_state_facts(object())
    assert (facts is not None) is complete
    if complete:
        assert facts["pitem_charges"] is None  # Hidden charge counts do not block inspection.


def test_changed_initial_facts_request_reobservation_without_context(monkeypatch):
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    state = SimpleNamespace(hand=[], public_info="catalog", legal_actions=lambda: ["drink:0", "skip"])
    events = []
    rec = SimpleNamespace(log=lambda kind, **kwargs: events.append((kind, kwargs)))
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "_detail_state_facts",
                        lambda _, **kw: {"hp": 20})
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


@pytest.mark.parametrize("customized", [True, False])
def test_vision_runs_only_for_customized_card_after_restoration(monkeypatch, customized):
    from hiro.brain import card_detail_transcription
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAIL_VISION", "1")
    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    identity = {"slot": 0, "card_id": "generic-id", "upgrade": 1}
    card = SimpleNamespace(**identity, available=True)
    state = SimpleNamespace(hand=[card], public_info="", legal_actions=lambda: ["play:0", "skip"])
    evidence = {**identity, "selected_card": identity, "detail_card": identity,
                "selection_verified": True, "snapshot_sha256": review.image_sha256(image),
                "detail_sha256": "a" * 64, "raw_ocr_lines": ["追加1"]}
    restored, calls, events = [], [], []
    def inspect(*args, **kwargs):
        kwargs["on_detail"](image, evidence)
        restored.append(True)
        return review.ReviewResult([evidence], image, [], True)
    def transcribe(llm, **kwargs):
        assert restored == [True]
        calls.append(kwargs)
        return {"status": "unavailable", "reason": "test_no_model"}
    monkeypatch.setattr(review, "review_exam_hand_details", inspect)
    monkeypatch.setattr(card_detail_transcription, "transcribe_card_detail", transcribe)
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "_detail_state_facts", lambda _, **kw: {"hp": 20})
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "device",
                        SimpleNamespace(screenshot=lambda: image, click=lambda _: None))
    rec = SimpleNamespace(log=lambda kind, **kw: events.append(kind))
    assert exam._review_current_card_details(state, SimpleNamespace(img=image), rec, llm=object(),
        produce={"deck": [{"card_id": "generic-id", "upgrade": 1, "customized": customized}]})
    assert len(calls) == int(customized)
    assert "追加1" in state.public_info  # Failure keeps original evidence.
    if customized:
        assert events.index("exam_card_detail_review") < events.index("exam_card_detail_transcription")


@pytest.mark.parametrize("screen,missing,attr,multiplier,gate", [
    (False, None, "dance", 1719, "exam_screen_unverified"),
    (True, "remaining_turns", "dance", 1719, "core_hud_unknown"),
    (True, "hp", "dance", 1719, "core_hud_unknown"),
    (True, "genki", "dance", 1719, "core_hud_unknown"),
    (True, None, None, 1719, "attribute_unknown"),
    (True, None, "dance", None, "multiplier_unknown"),
    (True, None, "dance", 1719, "verified")])
def test_state_gate_diagnostics_preserve_rejection_decisions(monkeypatch, screen, missing, attr, multiplier, gate):
    from hiro.vision import hif, observe
    reads = []
    raw = {"attr": attr, "multiplier_pct": multiplier, "multiplier_votes": [1719,1719]}
    facts = {"remaining_turns": 6, "hp":32, "genki":9}
    if missing:
        facts[missing] = None
    monkeypatch.setattr(hif, "is_hif_exam", lambda _: screen)
    monkeypatch.setattr(hif, "read_hif_exam", lambda *a, **kw: reads.append(True) or raw)
    monkeypatch.setattr(observe, "battle_observation", lambda _: dict(facts))
    diagnostic = {}
    result = exam._detail_state_facts(object(), diagnostics=diagnostic)
    assert (result is not None) is (gate == "verified")
    assert diagnostic["gate"] == gate
    assert diagnostic["exam_screen_verified"] is screen
    if screen:
        assert diagnostic["readings"] == {**facts, **raw}
    else:
        assert reads == []  # No full reader is run on an unverified page.


def test_state_changed_preserves_lossless_current_image_and_failed_gate(monkeypatch):
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS", "1")
    initial, fresh = np.zeros((2,2,3), np.uint8), np.ones((2,2,3), np.uint8)
    state = SimpleNamespace(hand=[], public_info="catalog", legal_actions=lambda:["drink:0","skip"])
    events = []
    def facts(image, *, diagnostics=None):
        diagnostics.update(gate="verified" if image is initial else "multiplier_unknown")
        return {"hp":32} if image is initial else None
    def inspect(*args, **kwargs):
        assert kwargs["same_state"](fresh) is False
        assert kwargs["same_state"](fresh) is False
        return review.ReviewResult([], fresh, ["initial_state_unverified"], False)
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "_detail_state_facts", facts)
    monkeypatch.setitem(exam._review_current_card_details.__globals__, "device",
                        SimpleNamespace(screenshot=lambda:fresh,click=lambda _:pytest.fail("no clicks")))
    monkeypatch.setattr(review,"review_exam_hand_details",inspect)
    assert exam._review_current_card_details(state, SimpleNamespace(img=initial),
        SimpleNamespace(log=lambda kind, **kw:events.append((kind,kw)))) is False
    kind, event = events[0]
    assert kind == "exam_card_detail_state_changed"
    assert event["image"] is fresh and event["lossless"] is True
    assert event["pixel_sha256"] == review.image_sha256(fresh)
    assert event["baseline_sha256"] == review.image_sha256(initial)
    assert event["diagnostics"]["gate"] == "multiplier_unknown"
    baselines = [data for kind, data in events if kind == "exam_card_detail_baseline"]
    assert len(baselines) == 1
    assert baselines[0]["image"] is initial and baselines[0]["lossless"] is True
    assert baselines[0]["pixel_sha256"] == event["baseline_sha256"]
    assert baselines[0]["facts"] == {"hp": 32}


@pytest.mark.synthetic
@pytest.mark.parametrize("enabled,restored", [(False,True),(True,True),(True,False)])
def test_visible_piles_require_opt_in_and_restored_state(monkeypatch,enabled,restored):
    from hiro.vision import exam_pile_snapshot
    monkeypatch.setenv("HIRO_EXAM_CARD_DETAILS","1")
    monkeypatch.setenv("HIRO_EXAM_PILE_SNAPSHOT","1" if enabled else "0")
    monkeypatch.delenv("HIRO_EXAM_CARD_DETAIL_VISION",raising=False)
    image=np.zeros((4,4,3),np.uint8)
    state=SimpleNamespace(hand=[],public_info="catalog",legal_actions=lambda:["play:0","skip"])
    events=[]
    snapshot={"active":True,"scope":"current_exam_groups","draw_order":"unknown",
              "groups":[{"pile":"draw","count":1,"complete":True,"cards":[{"card_id":"synthetic","observed_thumbnail_upgrade":1}]}],
              "snapshot_sha256":review.image_sha256(image)}
    monkeypatch.setattr(exam_pile_snapshot,"read_exam_visible_groups",lambda im:snapshot)
    def inspect(*args,**kw):
        assert ("on_opened" in kw) is enabled
        if enabled:kw["on_opened"](image)
        return review.ReviewResult([],image,[],restored)
    monkeypatch.setattr(review,"review_exam_hand_details",inspect)
    monkeypatch.setattr(exam,"_detail_state_facts",lambda img,**kw:{"hp":32})
    monkeypatch.setattr(exam,"device",SimpleNamespace(screenshot=lambda:image,click=lambda p:pytest.fail("no clicks")))
    rec=SimpleNamespace(log=lambda kind,**kw:events.append((kind,kw)))
    if not restored:
        with pytest.raises(ResumeBlocked):exam._review_current_card_details(state,SimpleNamespace(img=image),rec)
    else:
        assert exam._review_current_card_details(state,SimpleNamespace(img=image),rec)
    if enabled and restored:
        assert '"scope": "current_exam_groups"' in state.public_info
        event=next(kw for kind,kw in events if kind=="exam_pile_snapshot")
        assert event["lossless"] is True
        assert event["snapshot"]["exam_snapshot_sha256"]==review.image_sha256(image)
        assert event["snapshot"]["restoration_verified"] is True
    else:
        assert state.public_info=="catalog"
        assert not any(kind=="exam_pile_snapshot" for kind,_ in events)
