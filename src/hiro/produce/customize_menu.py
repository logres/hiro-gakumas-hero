"""Opt-in, single-level menu-session executor. All device operations are injected.

Review fields and reference_frame must come from the same previously reviewed menu
frame. No navigation, toast dismissal, retry, or purchase is implicit here.
"""
from dataclasses import dataclass, field

import numpy as np


class ReviewMismatch(ValueError):
    pass


@dataclass
class MenuEvidence:
    ok: bool = False
    status: str = "rejected"
    final_click_sent: bool = False
    taps: list = field(default_factory=list)
    confirmation: dict | None = None
    observation: dict | None = None
    error: str | None = None


def _require(condition, message):
    if not condition:
        raise ReviewMismatch(message)


def _int(value):
    return type(value) is int


def _validate_args(args):
    _require(args.get("menu_session") is True and args.get("strict") is True, "strict menu session required")
    _require(_int(args.get("levels")) and args["levels"] == 1, "exactly one level required")
    for key in ("upgrade", "item_index", "price"):
        _require(_int(args.get(key)) and args[key] >= 0, f"invalid {key}")
    for key in ("card_id", "customize_id"):
        _require(isinstance(args.get(key), str) and bool(args[key].strip()), f"invalid {key}")


def _selected(fields, args):
    _validate_args(args)
    _require(fields.get("view") == "menu", "current view is not menu")
    card = fields.get("selected_card") or {}
    for key in ("card_id", "upgrade"):
        _require(card.get(key) is not None and type(card[key]) is type(args.get(key)) and card[key] == args.get(key), f"card {key} mismatch")
    menu = fields.get("menu") or {}
    items = menu.get("items") or []
    selected = [it for it in items if it.get("selected") is True]
    _require(len(selected) == 1, "selection is not unique")
    item = selected[0]
    _require(menu.get("selected_item_index") == args.get("item_index") == item.get("item_index"), "physical selection mismatch")
    _require(sum(it.get("item_index") == item.get("item_index") for it in items) == 1, "duplicate physical index")
    _require(item.get("id") == args.get("customize_id") and bool(item.get("id")), "option id mismatch")
    _require(bool(item.get("name")), "missing option name")
    _require(_int(item.get("price")) and item["price"] == args.get("price") and item["price"] >= 0, "price mismatch")
    _require(item.get("available") is True and item.get("maxed") is False, "option unavailable")
    _require(_int(item.get("left")) and item["left"] > 0, "missing remaining count")
    _require(_int(menu.get("total_left")) and menu["total_left"] > 0, "missing total count")
    _require(_int(fields.get("produce_point")) and fields["produce_point"] >= item["price"], "balance unavailable or insufficient")
    return item


def validate_current(review, args, current, reference_frame, fresh_frame):
    """Pure preflight; returns selected option or raises before any operation."""
    _validate_args(args)
    old, new = _selected(review, args), _selected(current, args)
    for key in ("id", "name", "price", "left", "item_index"):
        _require(old.get(key) == new.get(key), f"reviewed option {key} changed")
    for key in ("produce_point", "cards_left"):
        _require(review.get(key) == current.get(key), f"reviewed {key} changed")
    _require(review["menu"]["total_left"] == current["menu"]["total_left"], "total count changed")
    a, b = np.asarray(reference_frame), np.asarray(fresh_frame)
    _require(a.shape == b.shape and a.ndim == 3 and a.shape[0] >= 743 and a.shape[1] >= 700, "invalid reference geometry")
    difference = np.abs(a[158:743, 20:700].astype(float) - b[158:743, 20:700].astype(float)).mean()
    _require(np.isfinite(difference) and difference <= 3, "reviewed effect panels changed")
    return new


def validate_confirmation(review, args, confirmation):
    """Require positive recognized identity, amounts, and unchecked suppression."""
    item = _selected(review, args)
    _validate_args(args)
    c = confirmation or {}
    for key in ("card_id", "upgrade", "price"):
        _require(c.get(key) is not None and type(c[key]) is type(args.get(key)) and c[key] == args.get(key), f"confirmation {key} mismatch")
    _require(c.get("option_name") == item["name"], "confirmation option mismatch")
    _require(c.get("suppress_confirmation") is False, "confirmation suppression must be unchecked")
    before = review["produce_point"]
    _require(_int(c.get("p_before")) and c["p_before"] == before, "confirmation balance mismatch")
    _require(_int(c.get("p_after")) and c["p_after"] == before - item["price"], "confirmation arithmetic mismatch")
    center = c.get("confirm_center")
    _require(isinstance(center, (tuple, list)) and len(center) == 2 and all(_int(v) for v in center) and 360 <= center[0] < 720 and 1000 <= center[1] < 1280, "invalid confirmation button")
    return c


def prepare_current(review, args, reference_frame, *, shoot, read, click, ocr, wait, read_confirm, attempts=5):
    """Open confirmation once, without buying. Callbacks receive the fresh frame."""
    result = MenuEvidence()
    try:
        frame = shoot()
        validate_current(review, args, read(frame), reference_frame, frame)
        buttons = [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for text, b in ocr(frame)
                   if text.replace(" ", "") == "実行する" and 1040 <= (b[1] + b[3]) // 2 <= 1120]
        _require(len(buttons) == 1, "execute button is not unique")
        result.taps.append(list(buttons[0]))
        click(*buttons[0])
        for _ in range(min(max(attempts, 1), 20)):
            wait(0.2)
            confirmation = read_confirm(shoot())
            if confirmation:
                result.confirmation = validate_confirmation(review, args, confirmation)
                result.ok, result.status = True, "confirmation_ready"
                return result
        result.status, result.error = "uncertain", "confirmation not positively observed"
    except ReviewMismatch as exc:
        result.error = str(exc)
        if result.taps:
            result.status = "uncertain"
    except Exception as exc:
        if not result.taps:
            raise
        result.status, result.error = "uncertain", f"confirmation-open click may have executed; do not repeat: {exc}"
    return result


def _positive_result(observation, review, args):
    if not observation:
        return False
    expected = review["produce_point"] - args["price"]
    toast = observation.get("toast") or {}
    exact = toast.get("card_id") == args["card_id"] and toast.get("upgrade") == args["upgrade"]
    if exact and observation.get("produce_point") == expected:
        return True
    menu = observation.get("menu") or {}
    card = observation.get("selected_card") or {}
    selected = next((it for it in menu.get("items", []) if it.get("item_index") == args["item_index"]), {})
    old = _selected(review, args)
    return (observation.get("view") == "menu" and card.get("card_id") == args["card_id"]
            and card.get("upgrade") == args["upgrade"] and observation.get("produce_point") == expected
            and selected.get("id") == args["customize_id"] and selected.get("left") == old["left"] - 1
            and menu.get("total_left") == review["menu"]["total_left"] - 1)


def _exact_toast(observation, args):
    toast = (observation or {}).get("toast") or {}
    return toast.get("card_id") == args["card_id"] and type(toast.get("upgrade")) is int and toast["upgrade"] == args["upgrade"]


def settle_current(prior, review, args, *, shoot, read_result, wait, dismiss_result=None, attempts=10):
    """Observe an already-sent purchase, optionally dismissing its exact result.

    ``dismiss_result(frame, observation)`` is explicit authorization for one result
    dismissal only. This function has no purchase-click callback and cannot retry
    the transaction. An exact toast may precede the refreshed HUD balance.
    """
    result = MenuEvidence(final_click_sent=prior.final_click_sent, taps=list(prior.taps),
                          confirmation=prior.confirmation, observation=prior.observation)
    try:
        _validate_args(args)
        _selected(review, args)
        _require(prior.final_click_sent is True, "no prior final click to settle")
        result.status = "uncertain"
        exact_seen = _exact_toast(prior.observation, args)
        dismissed = False
        expected = review["produce_point"] - args["price"]
        for _ in range(min(max(attempts, 1), 20)):
            wait(0.2)
            frame = shoot()
            result.observation = read_result(frame)
            current_exact = _exact_toast(result.observation, args)
            exact_seen = exact_seen or current_exact
            balance = (result.observation or {}).get("produce_point")
            if (_positive_result(result.observation, review, args)
                    or exact_seen and type(balance) is int and balance == expected):
                result.ok, result.status = True, "confirmed"
                return result
            if current_exact and dismiss_result is not None and not dismissed:
                dismissed = True  # transport uncertainty must never repeat dismissal
                dismiss_result(frame, result.observation)
        result.error = "final click already sent; no positive result observed; do not repeat"
    except ReviewMismatch as exc:
        result.error = str(exc)
    except Exception as exc:
        result.error = f"settlement uncertain; do not repeat purchase: {exc}"
    return result


def commit_current(review, args, *, shoot, read_confirm, click, wait, read_result, attempts=10, dismiss_result=None):
    """Validate current confirmation and send exactly one final click. Never retry it.

    read_result(frame) returns parsed fields, optionally with an exact-card toast
    under ``toast``. Missing positive evidence yields uncertain, never success.
    """
    result = MenuEvidence()
    try:
        result.confirmation = validate_confirmation(review, args, read_confirm(shoot()))
        center = result.confirmation["confirm_center"]
        result.taps.append(list(center))
        result.final_click_sent = True  # transport exceptions also prohibit blind retry
        result.status = "uncertain"
        click(*center)
        return settle_current(result, review, args, shoot=shoot, read_result=read_result,
                              wait=wait, attempts=attempts, dismiss_result=dismiss_result)
    except ReviewMismatch as exc:
        result.error = str(exc)
    except Exception as exc:
        if not result.final_click_sent:
            raise
        result.error = f"final click may have executed; do not repeat: {exc}"
    return result
