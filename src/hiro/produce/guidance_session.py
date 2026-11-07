"""Strict, image-backed SPECIAL_GUIDANCE visit; never invokes the legacy executor.

One model choice authorizes one next level. ``hooks`` exists for offline tests;
production callers need only a device and an explicitly safe ``leave`` callback.
All navigation uses freshly observed controls, with no fallback coordinates.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
import time

from hiro.brain.customize_card_selection import select_card
from hiro.brain.mechanism_customize import compare_options
from hiro.contracts import ActionKind, ExecutionResult
from hiro.produce.customize_menu import prepare_current, commit_current
from hiro.produce.customize_preview import collect_current_menu
from hiro.produce.guidance_grid import scan_guidance_grid, locate_guidance_card


def native_ocr(image):
    from hiro.vision.ocr import ocr_boxes
    return [(t, b) for t, _, b in ocr_boxes(image, scale=1)]


def read_current(image):
    """Native-scale DMM OCR, plus independent unique four-corner cursor proof."""
    import cv2
    from hiro.vision.customize import read_special_guidance, GRID_REGION, SCROLL_REGION, SCROLL_X
    from hiro.vision.deck import dialog_scroll, read_card_grid, _cursor_px, CURSOR_MIN_PX_118
    fields = read_special_guidance(image, native_ocr(image))
    if fields.get("view") == "select":
        fields.update(dialog_scroll(image, SCROLL_REGION, SCROLL_X))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        cells = read_card_grid(image, GRID_REGION, "guidance")
        fields["cursor_selected_indices"] = [c["index"] for c in cells
            if _cursor_px(hsv, c["rect"]) >= CURSOR_MIN_PX_118 * (c["rect"][2] / 118) ** 2]
    return fields


def read_confirm(image):
    from hiro.vision.customize_confirm import read_confirmation
    return read_confirmation(image, native_ocr(image))


def result_reader(read, ocr):
    def result(image):
        from hiro.vision.customize import read_customize_result
        fields = read(image)
        # Require the entire success sentence, not a substring of a menu label.
        rows = ocr(image)
        matches = [(t, b) for t, b in rows
                   if re.fullmatch(r".+をカスタマイズしました[。！!]?", t.replace(" ", ""))]
        # Native OCR splits this particular success bubble over adjacent lines.
        # Join only a unique pair inside its observed lower bubble region.
        bubble = sorted([(t.replace(" ", ""), b) for t, b in rows
                         if 950 <= b[1] < b[3] <= 1100], key=lambda r: (r[1][1], r[1][0]))
        for (a, box_a), (b, box_b) in zip(bubble, bubble[1:]):
            if (0 <= box_b[1] - box_a[3] <= 25
                    and max(box_a[0], box_b[0]) < min(box_a[2], box_b[2])
                    and re.fullmatch(r".+をカスタマイズしました[。！!]?", a+b)):
                matches.append((a+b, (min(box_a[0],box_b[0]), min(box_a[1],box_b[1]),
                                        max(box_a[2],box_b[2]), max(box_a[3],box_b[3]))))
        if len(matches) == 1:
            text, box = matches[0]
            toast = read_customize_result(text)
            if toast.get("card_id") and type(toast.get("upgrade")) is int:
                fields["toast"] = {**toast, "center": [(box[0]+box[2])//2, (box[1]+box[3])//2]}
        return fields
    return result


@dataclass
class Hooks:
    scan: object = scan_guidance_grid
    locate: object = locate_guidance_card
    pick: object = select_card
    collect: object = collect_current_menu
    compare: object = compare_options
    prepare: object = prepare_current
    commit: object = commit_current
    ocr: object = native_ocr
    confirm: object = read_confirm


def _key(card):
    if not card or not card.get("card_id") or type(card.get("upgrade")) is not int:
        raise ValueError("guidance card identity/version unknown")
    return card["card_id"], card["upgrade"]


def _button(image, text, ocr, *, lower=True):
    hits = [((b[0]+b[2])//2, (b[1]+b[3])//2) for t, b in ocr(image)
            if t.replace(" ", "") == text and (not lower or 1000 <= (b[1]+b[3])//2 < 1150)]
    if len(hits) != 1:
        raise ValueError("guidance control not uniquely observed: " + text)
    return hits[0]


def _choice(decision):
    if decision.action.kind == ActionKind.WAIT:
        if decision.action.args.get("choice") == "decline":
            return "decline"
        raise ValueError("guidance decision waits: " + decision.reason)
    if decision.action.kind != ActionKind.CUSTOMIZE_CARD:
        raise ValueError("unexpected guidance decision")
    return "customize"


def run(session, decider, identity, *, device, read=None, wait=time.sleep,
        leave=None, hooks=None, max_steps=12):
    """Finish a guidance visit, or raise without leaving on any uncertainty.

    ``device`` supplies screenshot/click/swipe. ``read`` returns raw current-page
    fields, including ``cursor_selected_indices`` for grid selection verification.
    A resumed menu may have unknown customization history: its actual before/after
    images are authoritative. No remaining counts or effects are inferred.
    """
    import cv2
    h, read = hooks or Hooks(), read or read_current
    reviewed, excluded = set(), set()
    known = {}
    shoot, click = device.screenshot, device.click
    common = dict(shoot=shoot, read=read, click=click, wait=wait)
    traversal = dict(shoot=shoot, read=read,
                     swipe=lambda *coords: device.swipe(*coords, duration=.6), wait=wait)

    def observe(image, fields):
        return session.observe(scene="SPECIAL_GUIDANCE", img=image, fields=deepcopy(fields), ready=True)

    def current():
        image = shoot()
        return image, read(image)

    def navigate(text, expected):
        image, fields = current()
        observe(image, fields)
        click(*_button(image, text, h.ocr))
        for _ in range(8):
            wait(.3)
            image, fields = current()
            if fields.get("view") == expected:
                observe(image, fields)
                session.record()
                return fields
        raise ValueError("guidance navigation not positively observed")

    def finish():
        if leave is None:
            raise ValueError("guidance exit requires an explicit safe leave callback")
        result = leave()
        if result is False or getattr(result, "ok", True) is False:
            raise ValueError("guidance exit was not verified")
        return True

    for _ in range(max_steps):
        image, fields = current()
        if fields.get("view") == "select":
            if fields.get("cards_left") == 0:
                observe(image, fields)
                session.record()
                return finish()
            scan = h.scan(**traversal)
            if scan.get("complete") is not True or scan.get("unknown_observations"):
                raise ValueError("guidance inventory incomplete or unknown")
            image, fields = current()
            if fields.get("view") != "select":
                raise ValueError("guidance grid changed during scan")
            fields.update(cards=scan["cards"], complete=True, guidance_scan=scan)
            known.update({_key(c): c.get("customized") for c in scan["cards"]})
            obs = observe(image, fields)
            decision = h.pick(decider, session.state, identity, scan["cards"], complete=True,
                              reviewed=reviewed, excluded=excluded)
            session.record(obs, decision=decision)
            if _choice(decision) == "decline":
                return finish()
            args = decision.action.args
            if args.get("review_only") is not True:
                raise ValueError("grid choice must authorize review only")
            key = _key(args)
            cell = h.locate(*key, scan=scan, **traversal)
            if cell is None or not cell.get("center"):
                raise ValueError("guidance target not freshly unique")
            click(*cell["center"])
            wait(.5)
            image, fields = current()
            cursors = fields.get("cursor_selected_indices")
            selected = [c for c in fields.get("cards") or [] if c.get("index") in (cursors or [])]
            if (fields.get("view") != "select" or _key(fields.get("selected_card")) != key
                    or len(cursors or []) != 1 or len(selected) != 1 or _key(selected[0]) != key):
                raise ValueError("guidance selection lacks exact unique cursor proof; no retry")
            navigate("カスタマイズ", "menu")
            image, fields = current()
            if _key(fields.get("selected_card")) != key:
                raise ValueError("opened guidance menu changed identity")
        elif fields.get("view") != "menu":
            raise ValueError("guidance view unknown")

        key = _key(fields.get("selected_card"))
        menu = fields.get("menu") or {}
        total = menu.get("total_left")
        items = menu.get("items") or []
        indices = [i.get("item_index") for i in items]
        all_maxed = (bool(items) and len(set(indices)) == len(indices)
                     and all(type(i.get("item_index")) is int and bool(i.get("id"))
                             and i.get("maxed") is True for i in items))
        if all_maxed:
            reviewed.add(key)
            navigate("一覧に戻る", "select")
            continue
        if type(total) is not int or total < 0:
            raise ValueError("guidance remaining count unknown")
        if total == 0:
            reviewed.add(key)
            navigate("一覧に戻る", "select")
            continue
        previews = h.collect(**common)
        if not previews:
            raise ValueError("guidance has no complete preview set")
        for preview in previews:
            if _key(preview.fields.get("selected_card")) != key:
                raise ValueError("guidance preview changed card")
            preview.fields["selected_card"]["customized"] = known.get(key)
            preview.fields["current_effects_observed"] = True
            obs = observe(preview.image, preview.fields)
            session.record(obs)  # persist every exact model image, including before/after
        ok, encoded = cv2.imencode(".jpg", cv2.hconcat([p.image for p in previews]))
        if not ok:
            raise ValueError("guidance comparison image encoding failed")
        decision = h.compare(decider, session.state, identity, [p.fields for p in previews], encoded.tobytes())
        session.record(decision=decision)
        if _choice(decision) == "decline":
            reviewed.add(key)
            excluded.add(key)
            navigate("一覧に戻る", "select")
            continue
        args = decision.action.args
        reference = [p for p in previews if p.fields["menu"].get("selected_item_index") == args.get("item_index")]
        if len(reference) != 1 or _key(args) != key:
            raise ValueError("guidance decision does not map to exact reviewed preview")
        reference = reference[0]
        image, fresh = current()
        if _key(fresh.get("selected_card")) != key or fresh.get("view") != "menu":
            raise ValueError("guidance menu changed before reselect")
        items = [i for i in (fresh.get("menu") or {}).get("items", []) if i.get("item_index") == args["item_index"]]
        if len(items) != 1:
            raise ValueError("guidance physical option missing")
        if items[0].get("selected") is not True:
            center = items[0].get("center")
            if not center or len(center) != 2 or not (30 <= center[0] <= 690 and 790 <= center[1] <= 920):
                raise ValueError("guidance option coordinate unknown")
            click(*center)
            wait(.7)
        obs = observe(reference.image, reference.fields)
        prepared = h.prepare(reference.fields, args, reference.image, **common, ocr=h.ocr, read_confirm=h.confirm)
        if not prepared.ok:
            execution = ExecutionResult(decision.action, False, taps=prepared.taps, error=prepared.error)
            session.record(obs, decision=decision, execution=execution)
            raise ValueError("guidance preparation stopped: " + str(prepared.error))

        dismissed = False

        def dismiss(frame, result):
            nonlocal dismissed
            toast = result.get("toast") or {}
            if dismissed or _key(toast) != key or not toast.get("center"):
                raise ValueError("guidance toast dismissal not precisely observed")
            dismissed = True  # transport exceptions prohibit another dismissal
            click(*toast["center"])

        read_result = result_reader(read, h.ocr)
        result = h.commit(reference.fields, args, shoot=shoot, click=click, wait=wait,
                          read_confirm=h.confirm, read_result=read_result, dismiss_result=dismiss)
        from hiro.brain.customization_context import enabled as customization_context_enabled
        from uuid import uuid4
        evidence = ({"transaction_id": str(uuid4()), "status": getattr(result, "status", None),
                     "final_click_sent": getattr(result, "final_click_sent", False), "source": "strict_menu_settlement"}
                    if customization_context_enabled() and result.ok and getattr(result, "status", None) == "confirmed"
                    and getattr(result, "final_click_sent", False) else None)
        session.record(obs, decision=decision, execution=ExecutionResult(
            decision.action, result.ok, customization_evidence=evidence, taps=prepared.taps + result.taps,
            page_before="SPECIAL_GUIDANCE", page_after="SPECIAL_GUIDANCE", error=result.error))
        if not result.ok:
            raise ValueError("guidance purchase uncertain; do not retry: " + str(result.error))
        known[key] = True
        # Settlement can positively confirm the refreshed balance before closing
        # the toast. Dismiss that exact observed bubble once before previewing.
        if not dismissed:
            image = shoot()
            result_fields = read_result(image)
            if result_fields.get("toast"):
                dismiss(image, result_fields)
                wait(.4)
        # Observe fresh P after recording the successful transaction/event. Remain
        # in this menu so the next iteration reviews all actual next-level options.
        image, fresh = current()
        observe(image, fresh)
        session.record()
        if fresh.get("view") != "menu" or _key(fresh.get("selected_card")) != key:
            raise ValueError("guidance purchase did not preserve observed menu")
    raise ValueError("guidance session step limit reached; stopped without exit")
