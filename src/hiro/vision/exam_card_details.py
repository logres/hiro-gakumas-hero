"""Offline evidence reader for the exam's grouped owned-card list.

Only the hand section is a regular grid. Raw detail OCR is evidence, never a
claim that icon-bearing effects or the card's semantics have been decoded.
"""
import re

import cv2
from cv2.typing import MatLike

from hiro.vision import deck
from hiro.vision.ocr import ocr_boxes

DETAIL_REGION = (20, 102, 700, 390)


def _lines(img, region):
    x1, y1, x2, y2 = region
    return [{"text": t, "confidence": float(p), "box": [a+x1, b+y1, c+x1, d+y1]}
            for t, p, (a, b, c, d) in ocr_boxes(img[y1:y2, x1:x2])]


def _selected(img, cards):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    e, size = deck.CURSOR_EXPAND, deck.CURSOR_CORNER
    orange = (hsv[:,:,0] >= 8) & (hsv[:,:,0] <= 22) & (hsv[:,:,1] >= 150) & (hsv[:,:,2] >= 180)
    hot = []
    for c in cards:
        x, y, n, _ = c["rect"]
        corners = ((x-e,y-e), (x+n+e-size,y-e),
                   (x-e,y+n+e-size), (x+n+e-size,y+n+e-size))
        # Same deck cursor color test, independently for all four corners.
        counts = [int(orange[b:b+size,a:a+size].sum())
                  if 0 <= a <= img.shape[1]-size and 0 <= b <= img.shape[0]-size else 0
                  for a,b in corners]
        c["cursor_corner_pixels"] = counts
        if all(p >= 100 for p in counts):
            hot.append(c["index"])
    return hot[0] if len(hot) == 1 else None


def is_exam_card_list(img: MatLike) -> bool:
    """Verify only the modal title and active tab, without reading its contents."""
    if img.shape[:2] != (1280, 720):
        return False
    if deck.is_deck_list(img):
        return True
    if not deck._tab_active(img):
        return False
    return any(re.sub(r"\s", "", line["text"]) == "所持スキルカード"
               for line in _lines(img, (40, 25, 300, 90)))


def read_exam_hand_details(img: MatLike, *, include_detail: bool = True) -> dict:
    """Read visible hand cells and the current detail without controlling a device.

    Coordinates: boxes/hand_region are global xyxy; card rects are xywh.
    layout_complete concerns visible hand count only; semantic_complete is
    always False. A detail belongs to a hand cell only with a unique cursor.
    include_detail=False reads fresh layout/art identities without effect OCR;
    callers needing unresolved identity recovery must rerun the full reader.
    """
    out = dict(active=False, hand_count=None, hand_region=None, headings=[], cards=[],
               selected=None, selected_card=None, detail=None, agree=None,
               detail_lines=[], layout_complete=False, identities_complete=False,
               semantic_complete=False, problems=[])
    if img.shape[:2] != (1280, 720):
        out["problems"].append("expected normalized 720x1280 screenshot")
        return out
    if not is_exam_card_list(img):
        out["problems"].append("owned-card title and active skill-card tab not verified")
        return out
    out["active"] = True
    if include_detail:
        out["detail_lines"] = _lines(img, DETAIL_REGION)
    for line in _lines(img, deck.LIST_VIEW):
        text = re.sub(r"\s", "", line["text"]).replace("（", "(").replace("）", ")")
        match = re.fullmatch(r"(手札|山札|捨札)\((\d+)\)", text)
        if match and line["box"][0] < 220:
            out["headings"].append(dict(line, pile=match[1], count=int(match[2])))
    headings = sorted(out["headings"], key=lambda h: h["box"][1])
    hand = [h for h in headings if h["pile"] == "手札"]
    if len(hand) != 1:
        out["problems"].append("unique exact hand heading not visible")
        return out
    hand = hand[0]
    out["hand_count"] = hand["count"]
    following = [h for h in headings if h["box"][1] > hand["box"][3] and h["pile"] in ("山札", "捨札")]
    if not following:
        out["problems"].append("next pile boundary not visible")
        return out
    region = (0, hand["box"][3], 720, following[0]["box"][1])
    out["hand_region"] = list(region)
    cards = [dict(c) for c in deck.read_card_grid(img, region, "list")
             if c["rect"][1] >= region[1] and c["rect"][1]+c["rect"][3] <= region[3]]
    out["cards"] = cards
    out["layout_complete"] = len(cards) == hand["count"]
    if not out["layout_complete"]:
        out["problems"].append("visible complete hand cells do not match heading count")
    out["selected"] = _selected(img, cards)
    ids = {c["card_id"] for c in cards if c.get("card_id")}
    # Identity is read only in the title band, never from effect text.
    hits = [hit for line in out["detail_lines"] if line["box"][1] < 170
            if (hit := deck.card_from_name(line["text"], ids)) is not None]
    unique = {(h["card_id"], h["upgrade"]) for h in hits}
    detail = hits[0] if len(unique) == 1 else None
    out["detail"] = detail
    cell = next((c for c in cards if c["index"] == out["selected"]), None)
    if cell is not None and detail is not None:
        if cell.get("card_id") is not None:
            out["agree"] = cell["card_id"] == detail["card_id"] and cell.get("upgrade") in (None, detail["upgrade"])
        if out["agree"] is not False:
            out["selected_card"] = dict(detail)
            if cell.get("card_id") is None:
                cell.update(detail, identity_basis="selected_cursor_and_exact_detail_name")
    elif cell is not None and cell.get("card_id") and cell.get("upgrade") is not None:
        out["selected_card"] = {k: cell[k] for k in ("card_id", "name", "upgrade")}
    if out["agree"] is False:
        out["problems"].append("selected cell and detail identity disagree")
    out["identities_complete"] = out["layout_complete"] and all(c.get("card_id") and type(c.get("upgrade")) is int for c in cards)
    return out



