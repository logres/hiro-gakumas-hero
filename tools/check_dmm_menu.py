"""Bounded real-game input check: open menu, then close only an OCR-confirmed button.

Requires the game at home and a prior probe screenshot from that home screen.
Never starts produce or accepts rewards. No automatic elevation.
"""
import json
import argparse
import time
from pathlib import Path
from unittest.mock import patch


def home_matches(frame, reference):
    import numpy as np
    if frame.shape != reference.shape:
        return False
    # Menu icon is shared across tabs; require the selected orange Home tab too.
    regions = [(slice(1180,1260),slice(610,700)), (slice(1125,1208),slice(325,395))]
    return all(float(np.abs(frame[r].astype(float)-reference[r].astype(float)).mean()) <= 12
               for r in regions)


def traced_click(device, window, x, y, output):
    import win32gui
    from kotonebot.interop.win import mouse
    physical = tuple(device.scaler.logic_to_physical((x,y)))
    hwnd = int(window.info.id)
    report = {'logical': [x,y], 'physical': physical,
              'expected_screen': win32gui.ClientToScreen(hwnd, physical), 'events': []}
    move, down, up = mouse.set_pos, mouse.down, mouse.up
    def record(phase):
        report['events'].append({'phase': phase, 'cursor': win32gui.GetCursorPos(),
                                 'origin': win32gui.ClientToScreen(hwnd,(0,0)),
                                 'foreground_is_target': win32gui.GetForegroundWindow()==hwnd})
    def moving(*args, **kwargs):
        report['requested_move'] = list(args)
        move(*args, **kwargs)
        record('move')
    def pressing(*args, **kwargs):
        record('down')
        if tuple(win32gui.GetCursorPos()) != tuple(report['expected_screen']):
            raise RuntimeError('Cursor not at expected target; button-down blocked')
        down(*args, **kwargs)
    def releasing(*args, **kwargs):
        record('up')
        up(*args, **kwargs)
    try:
        with patch.object(mouse,'set_pos',moving), patch.object(mouse,'down',pressing), patch.object(mouse,'up',releasing):
            device.click(x,y)
    finally:
        record('after_click')
        output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'input_diagnostic':report}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=['windows_native','windows_sendinput'], default='windows_native')
    args = parser.parse_args()
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
    device = connect(args.backend)
    try:
        before = device.screenshot()
        cv2.imwrite(str(root / 'menu-before-check.png'), before)
        if not home_matches(before, reference):
            raise RuntimeError('Selected Home tab/menu not confirmed; no input sent')
        traced_click(device, window, 653, 1216, root / 'menu-input.json')
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
        if not home_matches(closed, reference):
            raise RuntimeError('Close click sent but return to home not confirmed')
        print('DMM menu open/close PASSED: two bounded clicks, no produce or purchases')
    finally:
        device.stop()


if __name__ == '__main__':
    main()
