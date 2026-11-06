"""Bounded real-game input check: open menu, then close only an OCR-confirmed button.

Requires the game at home and a prior probe screenshot from that home screen.
Never starts produce or accepts rewards. No automatic elevation.
"""
import json
import time
from pathlib import Path


def main():
    import cv2
    import numpy as np
    from hiro.platforms.windows.device import connect
    from hiro.platforms.windows.ocr import ocr_boxes
    from hiro.platforms.windows.target import ensure_input_access, resolve

    window, _ = resolve()
    ensure_input_access(window)
    root = Path('reports/windows-probe')
    reference = cv2.imread(str(root / 'logical.png'))
    if reference is None or reference.shape != (1280, 720, 3):
        raise RuntimeError('A 720x1280 home probe screenshot is required before this test')
    crop = (slice(1180, 1260), slice(610, 700))
    device = connect()
    try:
        before = device.screenshot()
        if before.shape != reference.shape:
            raise RuntimeError('Unexpected layout; no input sent')
        delta = float(np.abs(before[crop].astype(float) - reference[crop].astype(float)).mean())
        if delta > 12:
            raise RuntimeError('Home menu icon changed; no input sent')
        device.click(653, 1216)
        time.sleep(1)
        opened = device.screenshot()
        cv2.imwrite(str(root / 'menu-open-check.png'), opened)
        boxes = ocr_boxes(opened, scale=1)
        texts = [t.replace(' ', '') for t, _, _ in boxes]
        (root / 'menu-ocr.json').write_text(json.dumps(boxes, ensure_ascii=False, indent=2), encoding='utf-8')
        if not any('メニュー' in t for t in texts):
            raise RuntimeError('Menu not confirmed after one click; no retry or further input')
        close = [(score, box) for text, score, box in boxes
                 if text.replace(' ', '') == '閉じる' and score >= .8 and box[1] > 640]
        if len(close) != 1:
            raise RuntimeError('Menu opened, but no unique close button recognized; left open for manual close')
        _, (x1, y1, x2, y2) = close[0]
        fresh = device.screenshot()
        if fresh.shape != opened.shape or float(np.abs(
                fresh[y1:y2,x1:x2].astype(float)-opened[y1:y2,x1:x2].astype(float)).mean()) > 12:
            raise RuntimeError('Close button changed; left menu open without another click')
        device.click((x1+x2)//2, (y1+y2)//2)
        time.sleep(1)
        closed = device.screenshot()
        cv2.imwrite(str(root / 'menu-closed-check.png'), closed)
        if closed.shape != reference.shape or float(np.abs(
                closed[crop].astype(float)-reference[crop].astype(float)).mean()) > 12:
            raise RuntimeError('Close click sent but return to home not confirmed')
        print('DMM menu open/close PASSED: two bounded clicks, no produce or purchases')
    finally:
        device.stop()


if __name__ == '__main__':
    main()
