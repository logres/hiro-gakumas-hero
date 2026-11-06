"""Fail-closed reader for the observed 720x1280 customization confirmation."""
from __future__ import annotations
import re
import numpy as np

TITLE = "カスタマイズ実行確認"
PRICE_BOX = (330, 398, 405, 441)
BEFORE_BOX = (200, 850, 335, 935)
AFTER_BOX = (460, 850, 600, 935)


def numeric_consensus(img, box):
    """Read black digits on the gray balance band using independent engines."""
    from hiro.vision.ocr import ocr
    from hiro.vision.digits import read_dddd
    x, y, X, Y = box
    try:
        text = "".join(t for t, _ in ocr(img[y:Y, x:X], languages=("en-US",)))
        clean = text.replace(",", "").strip()
        first = int(clean) if re.fullmatch(r"[0-9]+", clean) else None
        second = read_dddd(img, box)
    except Exception:
        return None
    return first if first is not None and first == second else None


def checkbox_state(img):
    """Recognize the white check stroke; unrecognized/animated pixels stay unknown."""
    if img.shape[:2] != (1280, 720):
        return None
    crop = img[993:1014, 229:251, :3]
    white = crop.min(axis=2) > 240
    # Both toggle states retain the tick. The observed gray/orange/gray
    # cycle establishes gray inactive and orange active (pending purchase proof).
    stroke = [(4, 11), (7, 14), (10, 11), (14, 7), (17, 4)]
    if not all(white[max(0,y-1):y+2,max(0,x-1):x+2].any() for x,y in stroke):
        return None
    b,g,r = crop[:,:,0],crop[:,:,1],crop[:,:,2]
    orange = (r>225)&(g>55)&(g<175)&(b<70)
    gray = (np.abs(r.astype(int)-g.astype(int))<8)&(np.abs(g.astype(int)-b.astype(int))<8)&(r>185)&(r<225)
    if orange.mean()>0.45:
        return True
    if gray.mean()>0.45:
        return False
    return None


def read_confirmation(img, boxes=None, *, numeric_reader=None, card_resolver=None):
    """Return verified fields or None. No inferred balances or fixed click fallback.

    boxes accepts (text, box) or the platform OCR's (text, confidence, box).
    numeric_reader(img, box) must provide independent numeric consensus.
    """
    if img is None or img.shape[:2] != (1280, 720):
        return None
    if boxes is None:
        from hiro.vision.ocr import ocr_boxes
        boxes = ocr_boxes(img)
    rows = [(r[0], r[-1]) for r in boxes]
    def one(region, predicate=lambda t: True):
        x,y,X,Y = region
        matches = [(t,b) for t,b in rows if x <= b[0] < b[2] <= X and y <= b[1] < b[3] <= Y and predicate(t)]
        return matches[0] if len(matches)==1 else None
    if not one((30,180,680,245), lambda t:t==TITLE):
        return None
    option = one((250,335,470,400))
    price = one((300,400,425,445), lambda t:bool(re.fullmatch(r"[0-9]+",t)))
    card = one((205,505,675,552))
    confirm = one((400,1120,640,1200), lambda t:t=="実行する")
    cancel = one((100,1120,340,1200), lambda t:t in ("キャンセル", "メキャンセル"))
    label = one((250,975,500,1025), lambda t:t=="次回以降表示しない")
    if not all((option,price,card,confirm,cancel,label)):
        return None
    if card_resolver is None:
        from hiro.vision.deck import card_from_name
        card_resolver = card_from_name
    try:
        identity = card_resolver(card[0])
    except Exception:
        return None
    if not identity or identity.get("upgrade") is None or not identity.get("card_id"):
        return None
    reader = numeric_reader or numeric_consensus
    before, after = reader(img, BEFORE_BOX), reader(img, AFTER_BOX)
    # Full-frame Japanese OCR can read this actual 70 as 10. Read the
    # price independently, using the same strict two-engine agreement.
    cost = reader(img, PRICE_BOX)
    if any(type(v) is not int for v in (before,after,cost)) or cost <= 0 or after < 0 or before-after != cost:
        return None
    def center(row):
        b=row[1]
        return ((b[0]+b[2])//2, (b[1]+b[3])//2)
    return {"card_id":identity["card_id"], "upgrade":identity["upgrade"],
            "option_name":option[0], "price":cost, "p_before":before, "p_after":after,
            "confirm_center":center(confirm), "cancel_center":center(cancel),
            "suppress_confirmation":checkbox_state(img)}


read_customize_confirmation = read_confirmation
