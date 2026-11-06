"""Bounded, read-only traversal of the SPECIAL_GUIDANCE selection grid.

All coordinates in ``screens`` and locate results belong to that fresh screenshot.
Aggregate cards deliberately carry no click coordinates or grid indices.
"""
from __future__ import annotations

from copy import deepcopy

SCROLL_REGION = (0, 625, 720, 988)
SCROLL_X = 702


def _move(swipe, wait, down):
    swipe(650, 880 if down else 760, 650, 760 if down else 880)
    wait(0.4)


def _snapshot(shoot, read):
    result = deepcopy(read(shoot()))
    if result.get("view") != "select":
        raise ValueError("SPECIAL_GUIDANCE select view required")
    return result


def _top(shoot, read, swipe, wait, limit):
    for n in range(limit + 1):
        snap = _snapshot(shoot, read)
        if snap.get("at_top") is True:
            return snap
        if n < limit:
            _move(swipe, wait, False)
    return snap


def scan_guidance_grid(*, shoot, read, swipe, wait, max_scrolls=12):
    """Read top through verified bottom, then restore top, even after read errors.

    ``read(image)`` returns the vision dict plus explicit ``at_bottom`` from
    ``dialog_scroll(image, SCROLL_REGION, SCROLL_X)``. Deck size is irrelevant.
    No taps, purchases, or game state mutations are performed.
    """
    from hiro.vision.deck import _block_match, merge_dialog_screens

    if max_scrolls < 0:
        raise ValueError("max_scrolls must be nonnegative")
    screens, problems = [], []
    restored = False
    try:
        snap = _top(shoot, read, swipe, wait, max_scrolls)
        initial_top = snap.get("at_top") is True
        if not initial_top:
            problems.append("initial_top_unverified")
        for n in range(max_scrolls + 1):
            screens.append(snap)
            if snap.get("at_bottom") is True:
                break
            if n < max_scrolls:
                _move(swipe, wait, True)
                snap = _snapshot(shoot, read)
        bottom = screens[-1].get("at_bottom") is True
        if not bottom:
            problems.append("final_bottom_unverified_or_scroll_limit")
        merged = merge_dialog_screens([s.get("cards") or [] for s in screens])
        problems.extend(merged["problems"])
        # Recover source-local positions only inside observations, never as global
        # click positions. Existing merger preserves the source screen number.
        row_count, offsets = 0, []
        for screen, added in zip(screens, merged["new_rows"], strict=True):
            rows = sorted({c["row"] for c in screen.get("cards") or []})
            row_count += added
            offsets.append((row_count - len(rows), rows))
        # Repeated identical row patterns can admit several overlap sizes.
        # Do not infer unique physical instances from the merger's longest fit.
        accumulated = []
        for screen in screens:
            groups = {}
            for cell in screen.get("cards") or []:
                groups.setdefault(cell["row"], []).append(cell)
            rows_here = [sorted(groups[r], key=lambda c: c["col"]) for r in sorted(groups)]
            fits = [k for k in range(1, min(len(accumulated), len(rows_here)) + 1)
                    if _block_match(accumulated[-k:], rows_here[:k])]
            if len(fits) > 1:
                problems.append("ambiguous_row_overlap")
            accumulated.extend(rows_here[max(fits, default=0):])
        cards = []
        for c in merged["cards"]:
            si = c["screen"]
            offset, rows = offsets[si]
            local_row = rows[c["row"] - offset]
            matches = [(i, x) for i, x in enumerate(screens[si]["cards"])
                       if x["row"] == local_row and x["col"] == c["col"]]
            if len(matches) != 1:
                problems.append("source_mapping_ambiguous")
                continue
            li, source = matches[0]
            metadata = {k: deepcopy(v) for k, v in source.items()
                        if k not in {"index", "row", "col", "center", "rect"}}
            cards.append({**metadata, "instance_index": len(cards),
                          "screen_index": si, "screen_local_index": source.get("index", li)})
        unknown = [{"screen_index": si, "screen_local_index": c.get("index", i)}
                   for si, s in enumerate(screens) for i, c in enumerate(s.get("cards") or [])
                   if c.get("card_id") is None or type(c.get("upgrade")) is not int]
    finally:
        restored = _top(shoot, read, swipe, wait, max_scrolls).get("at_top") is True
    if not restored:
        problems.append("return_top_unverified")
    return {"cards": cards, "screens": screens, "unknown_observations": unknown,
            "coverage_complete": initial_top and bottom, "returned_to_top": restored,
            "complete": bool(merged["complete"] and initial_top and bottom and restored and not problems),
            "problems": problems}


def locate_guidance_card(card_id, upgrade, *, shoot, read, swipe, wait,
                         max_scrolls=12, scan=None):
    """Return a fresh unique available match; never tap or use cached centers.

    A complete aggregate scan is required to prove global uniqueness. With no
    scan supplied this function obtains one. Leaves the grid at the found card.
    """
    scan = scan if scan is not None else scan_guidance_grid(
        shoot=shoot, read=read, swipe=swipe, wait=wait, max_scrolls=max_scrolls)
    candidates = [c for c in scan.get("cards", []) if c.get("card_id") == card_id
                  and c.get("upgrade") == upgrade and c.get("available") is True]
    if not scan.get("complete") or len(candidates) != 1:
        return None
    snap = _top(shoot, read, swipe, wait, max_scrolls)
    if snap.get("at_top") is not True:
        return None
    for n in range(max_scrolls + 1):
        matches = [c for c in snap.get("cards") or [] if c.get("card_id") == card_id
                   and c.get("upgrade") == upgrade and c.get("available") is True]
        if len(matches) > 1:
            return None
        if len(matches) == 1:
            return deepcopy(matches[0])
        if snap.get("at_bottom") is True or n == max_scrolls:
            return None
        _move(swipe, wait, True)
        snap = _snapshot(shoot, read)
