from copy import deepcopy

import numpy as np
import pytest

from hiro.produce.customize_menu import MenuEvidence, ReviewMismatch, commit_current, prepare_current, settle_current, validate_current


@pytest.fixture
def session():
    args = dict(menu_session=True, strict=True, levels=1, card_id="card", upgrade=1,
                item_index=0, price=40, customize_id="option")
    fields = dict(view="menu", produce_point=100, cards_left=2,
                  selected_card=dict(card_id="card", upgrade=1),
                  menu=dict(total_left=3, selected_item_index=0, items=[dict(
                      item_index=0, id="option", name="元気追加", price=40, left=2,
                      selected=True, available=True, maxed=False)]))
    confirm = dict(card_id="card", upgrade=1, option_name="元気追加", price=40,
                   p_before=100, p_after=60, suppress_confirmation=False,
                   confirm_center=[500, 1160], cancel_center=[200, 1160])
    return args, fields, confirm, np.zeros((1280, 720, 3), dtype=np.uint8)


@pytest.mark.parametrize("change", ["balance", "left", "name", "version", "selection", "panels"])
def test_stale_review_never_clicks(session, change):
    args, fields, confirm, frame = session
    current, fresh, taps = deepcopy(fields), frame.copy(), []
    if change == "balance": current["produce_point"] = 101
    if change == "left": current["menu"]["items"][0]["left"] = 1
    if change == "name": current["menu"]["items"][0]["name"] = "changed"
    if change == "version": current["selected_card"]["upgrade"] = 0
    if change == "selection": current["menu"]["selected_item_index"] = None
    if change == "panels": fresh[158:743, 20:700] = 4
    r = prepare_current(fields, args, frame, shoot=lambda: fresh, read=lambda _: current,
                        click=lambda *p: taps.append(p), ocr=lambda _: [("実行する", (400, 1060, 600, 1100))],
                        wait=lambda _: None, read_confirm=lambda _: confirm)
    assert not r.ok and taps == []


def test_prepare_only_opens_confirmation(session):
    args, fields, confirm, frame = session
    taps = []
    r = prepare_current(fields, args, frame, shoot=lambda: frame, read=lambda _: fields,
                        click=lambda *p: taps.append(p), ocr=lambda _: [("実行する", (400, 1060, 600, 1100))],
                        wait=lambda _: None, read_confirm=lambda _: confirm)
    assert r.ok and r.status == "confirmation_ready" and not r.final_click_sent
    assert taps == [(500, 1080)]


def test_duplicate_execute_buttons_reject(session):
    args, fields, confirm, frame = session
    taps = []
    r = prepare_current(fields, args, frame, shoot=lambda: frame, read=lambda _: fields,
                        click=lambda *p: taps.append(p),
                        ocr=lambda _: [("実行する", (400, 1060, 600, 1100))] * 2,
                        wait=lambda _: None, read_confirm=lambda _: confirm)
    assert not r.ok and not taps


@pytest.mark.parametrize("key,value", [("suppress_confirmation", True), ("suppress_confirmation", None),
                                    ("p_after", 61), ("price", None), ("card_id", "other"),
                                    ("upgrade", 0), ("option_name", "other")])
def test_bad_confirmation_never_commits(session, key, value):
    args, fields, confirm, frame = session
    confirm[key] = value
    taps = []
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: taps.append(p), wait=lambda _: None, read_result=lambda _: {})
    assert not r.ok and not r.final_click_sent and not taps


def test_uncertain_does_not_retry_or_navigate(session):
    args, fields, confirm, frame = session
    taps = []
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: taps.append(p), wait=lambda _: None, read_result=lambda _: {})
    assert not r.ok and r.final_click_sent and r.status == "uncertain"
    assert taps == [(500, 1160)]


def test_exact_toast_and_expected_balance_confirm(session):
    args, fields, confirm, frame = session
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: None, wait=lambda _: None,
                       read_result=lambda _: dict(toast=dict(card_id="card", upgrade=1), produce_point=60))
    assert r.ok and r.final_click_sent


def test_wrong_toast_not_success(session):
    args, fields, confirm, frame = session
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: None, wait=lambda _: None,
                       read_result=lambda _: dict(toast=dict(card_id="other", upgrade=1), produce_point=60))
    assert not r.ok and r.final_click_sent


def test_menu_decrement_confirms_without_toast(session):
    args, fields, confirm, frame = session
    after = deepcopy(fields)
    after["produce_point"] = 60
    after["menu"]["total_left"] = 2
    after["menu"]["items"][0]["left"] = 1
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: None, wait=lambda _: None, read_result=lambda _: after)
    assert r.ok


def test_click_exception_preserves_uncertainty(session):
    args, fields, confirm, frame = session
    def click(*_):
        raise OSError("transport disconnected")
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=click, wait=lambda _: None, read_result=lambda _: {})
    assert r.final_click_sent and r.status == "uncertain" and "do not repeat" in r.error


@pytest.mark.parametrize("key", ["levels", "upgrade", "item_index", "price"])
def test_boolean_args_never_commit(session, key):
    args, fields, confirm, frame = session
    args[key] = True
    taps = []
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: taps.append(p), wait=lambda _: None, read_result=lambda _: {})
    assert not r.ok and not r.final_click_sent and not taps


def test_prepare_transport_exception_is_uncertain(session):
    args, fields, confirm, frame = session
    def click(*_):
        raise OSError("transport disconnected")
    r = prepare_current(fields, args, frame, shoot=lambda: frame, read=lambda _: fields,
                        click=click, ocr=lambda _: [("実行する", (400, 1060, 600, 1100))],
                        wait=lambda _: None, read_confirm=lambda _: confirm)
    assert r.status == "uncertain" and not r.final_click_sent and len(r.taps) == 1


def test_settle_carries_prior_toast_to_delayed_balance(session):
    args, fields, confirm, frame = session
    prior = MenuEvidence(status="uncertain", final_click_sent=True,
                         observation=dict(toast=dict(card_id="card", upgrade=1), produce_point=100))
    r = settle_current(prior, fields, args, shoot=lambda: frame, wait=lambda _: None,
                       read_result=lambda _: dict(produce_point=60, menu=dict(total_left=None)))
    assert r.ok and r.final_click_sent


def test_delayed_balance_requires_explicit_dismissal_callback(session):
    args, fields, confirm, frame = session
    dismissals, taps = [], []
    def read(_):
        return dict(produce_point=60) if dismissals else dict(produce_point=100, toast=dict(card_id="card", upgrade=1))
    r = commit_current(fields, args, shoot=lambda: frame, read_confirm=lambda _: confirm,
                       click=lambda *p: taps.append(p), wait=lambda _: None, read_result=read,
                       dismiss_result=lambda frame, observation: dismissals.append(observation))
    assert r.ok and len(dismissals) == 1 and taps == [(500, 1160)]


def test_no_exact_toast_never_dismisses_or_claims_balance_only_success(session):
    args, fields, confirm, frame = session
    dismissals = []
    r = settle_current(MenuEvidence(final_click_sent=True), fields, args,
                       shoot=lambda: frame, read_result=lambda _: dict(produce_point=60), wait=lambda _: None,
                       dismiss_result=lambda *p: dismissals.append(p))
    assert not r.ok and r.status == "uncertain" and not dismissals


def test_settle_without_prior_purchase_rejects_without_reading(session):
    args, fields, confirm, frame = session
    reads = []
    r = settle_current(MenuEvidence(), fields, args, shoot=lambda: reads.append(1),
                       read_result=lambda _: {}, wait=lambda _: None)
    assert not r.ok and not r.final_click_sent and not reads
