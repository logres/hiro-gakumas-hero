"""Bounded, read-only hand-detail inspection with injected device operations.

No game actions, scrolling, reopening, or persistent evidence cache live here.
The caller must stop execution when ``restored`` is false.
"""
from dataclasses import dataclass
import hashlib


def image_sha256(image) -> str:
    """Bind evidence to the exact decision image bytes (not a perceptual hash)."""
    return hashlib.sha256(image.tobytes()).hexdigest()


@dataclass
class ReviewResult:
    evidence: list[dict]
    image: object
    problems: list[str]
    restored: bool


def _close_buttons(image):
    from hiro.vision.ocr import ocr_boxes
    return [((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
            for text, confidence, box in ocr_boxes(image, scale=1.0)
            if confidence >= 0.8 and "".join(text.split()) == "閉じる"]


def _get(card, key):
    return card.get(key) if isinstance(card, dict) else getattr(card, key, None)


def _identity(card):
    return _get(card, "card_id"), _get(card, "upgrade")


def review_exam_hand_details(initial_image, hand, *, shoot, click, sleep,
                             same_state, read_details=None, find_button=None,
                             close_buttons=None, on_detail=None, read_layout=None,
                             is_active=None, max_polls=8, poll_gap=0.2):
    """Inspect unambiguous identities, close once, verify full decision state.

    ``same_state(image)`` must compare the complete observed decision state to
    the initial state, without updating memory. All callbacks use supplied images.
    ``click`` accepts one recognized (x,y) tuple. Any uncertainty drops evidence.
    """
    if read_details is None:
        from hiro.vision.exam_card_details import read_exam_hand_details, is_exam_card_list
        read_details = read_exam_hand_details
        if read_layout is None:
            read_layout = lambda image: read_exam_hand_details(image, include_detail=False)
        if is_active is None:
            is_active = is_exam_card_list
    # Injected readers retain their original behavior unless fast paths are
    # explicitly supplied, so test doubles need not implement extra APIs.
    read_layout = read_layout or read_details
    is_active = is_active or (lambda image: read_details(image).get("active", False))
    if find_button is None:
        from hiro.vision.deck import find_deck_button
        find_button = find_deck_button
    close_buttons = close_buttons or _close_buttons
    max_polls = max(1, min(int(max_polls), 30))
    problems, evidence = [], []
    image = initial_image
    opened = False
    restored = False
    token = image_sha256(initial_image)

    def wait_active():
        nonlocal image
        for _ in range(max_polls):
            sleep(poll_gap)
            image = shoot()
            reading = read_layout(image)
            if reading.get("active"):
                return reading
        return None

    try:
        image = shoot()
        if not same_state(image):
            return ReviewResult([], image, ["initial_state_unverified"], False)
        button = find_button(image)
        if button is None:
            return ReviewResult([], image, ["detail_button_missing"], True)
        click(button)
        opened = True
        reading = wait_active()
        if reading is None:
            raise ValueError("detail_open_timeout")
        if not reading.get("layout_complete") or reading.get("hand_count") != len(hand):
            raise ValueError("hand_layout_incomplete")
        # Duplicate physical copies cannot be bound to a particular hand slot.
        keys = [_identity(c) for c in hand]
        slots = [_get(c, "slot") for c in hand]
        if len(set(slots)) != len(slots):
            raise ValueError("duplicate_hand_slots")
        for card, key in zip(hand, keys):
            if not key[0] or type(key[1]) is not int or key[1] < 0 or keys.count(key) != 1:
                problems.append("ambiguous_hand_identity")
                continue
            # Never reuse a center from the previous selected-card image.
            image = shoot()
            current = read_layout(image)
            if any(not c.get("card_id") or type(c.get("upgrade")) is not int
                   for c in current.get("cards", [])):
                # Full selected-detail recovery may identify an ambiguous art
                # cell. Use the SAME fresh screenshot, never a previous frame.
                current = read_details(image)
            cells = current.get("cards", [])
            if not current.get("active") or not current.get("layout_complete") or current.get("hand_count") != len(hand):
                raise ValueError("hand_layout_changed")
            matches = [c for c in cells if _identity(c) == key]
            if len(matches) != 1 or not matches[0].get("center"):
                raise ValueError("hand_identity_not_unique")
            cell = matches[0]
            click(tuple(cell["center"]))
            verified = None
            for _ in range(max_polls):
                sleep(poll_gap)
                image = shoot()
                detail = read_details(image)
                selected = [c for c in detail.get("cards", []) if c.get("index") == detail.get("selected")]
                if (detail.get("active") and detail.get("layout_complete") and detail.get("agree") is True
                        and len(selected) == 1 and _identity(selected[0]) == key
                        and _identity(detail.get("selected_card") or {}) == key
                        and _identity(detail.get("detail") or {}) == key):
                    verified = detail
                    break
            if verified is None:
                raise ValueError("selected_detail_identity_mismatch")
            raw = [line["text"] for line in verified.get("detail_lines", [])
                   if isinstance(line.get("text"), str) and line["text"].strip()]
            if not raw:
                raise ValueError("detail_text_missing")
            identity = {"slot": _get(card, "slot"), "card_id": key[0], "upgrade": key[1]}
            evidence.append({**identity, "selected_card": dict(identity), "detail_card": dict(identity),
                             "selection_verified": True, "snapshot_sha256": token,
                             "detail_sha256": image_sha256(image), "hash_basis": "pixelbytes",
                             "raw_ocr_lines": raw})
            if on_detail is not None:
                on_detail(image, evidence[-1])
    except Exception as exc:
        problems.append(str(exc) or type(exc).__name__)
        evidence = []
    finally:
        if opened:
            try:
                image = shoot()
                # No fixed close coordinate, escape, or secondary close attempt.
                if is_active(image):
                    buttons = close_buttons(image)
                    if len(buttons) == 1:
                        click(tuple(buttons[0]))
                    else:
                        raise ValueError("close_button_not_unique")
                for _ in range(max_polls):
                    sleep(poll_gap)
                    image = shoot()
                    if not is_active(image) and same_state(image):
                        restored = True
                        break
                if not restored:
                    problems.append("original_exam_state_not_restored")
            except Exception as exc:
                problems.append(str(exc) or type(exc).__name__)
    if not restored:
        evidence = []
    return ReviewResult(evidence, image, problems, restored)
