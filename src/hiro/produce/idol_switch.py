"""Opt-in handling of the pre-produce idol-switch offer; retain the chosen card."""
import time

import numpy as np


TITLE = "プロデュースアイドル変更"
BODY = "新しく切り替え可能なプロデュースアイドルを入手しています。"


def _norm(text):
    return "".join(text.split())


def decline_box(boxes):
    """Only the observed offer and its unique decline label qualify."""
    texts = [_norm(t) for t, _, _ in boxes]
    if TITLE not in texts or BODY not in "".join(texts):
        return None
    found = [tuple(b) for t, score, b in boxes
             if _norm(t) in ("切り替えない", "メ切り替えない") and score >= .8
             and 0 <= b[0] < b[2] <= 720 and 0 <= b[1] < b[3] <= 1280]
    return found[0] if len(found) == 1 else None


def decline_offer(*, shoot, ocr, click):
    """Observe twice and click once; changed/missing evidence sends no input."""
    before = shoot()
    box = decline_box(ocr(before))
    if box is None:
        return False
    fresh = shoot()
    if decline_box(ocr(fresh)) != box or before.shape != fresh.shape:
        return False
    x1, y1, x2, y2 = box
    a, b = before[y1:y2, x1:x2], fresh[y1:y2, x1:x2]
    if not a.size or np.mean(np.abs(a.astype(float) - b.astype(float))) > 3:
        return False
    click((x1 + x2) // 2, (y1 + y2) // 2)
    return True


class Step2Wait:
    """Intercept the blocking wait immediately after KAA clicks Step 1 Next."""
    _hiro_idol_switch = True

    def __init__(self, original):
        self.original = original

    def __getattr__(self, name):
        return getattr(self.original, name)

    def wait(self, *args, **kwargs):
        import os

        if os.environ.get("HIRO_DECLINE_IDOL_SWITCH") == "1":
            from kotonebot import device
            from hiro.produce.ops import ocr_boxes

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                device.screenshot()
                if self.original.exists():
                    break
                if decline_offer(shoot=device.screenshot, ocr=ocr_boxes, click=device.click):
                    break  # One bounded decline; original wait verifies transition.
                time.sleep(.3)
        return self.original.wait(*args, **kwargs)
