"""Bounded real-game input check: open menu, then close its OCR-confirmed X.

Requires the game at home and a prior probe screenshot from that home screen.
Never starts produce or accepts rewards. No automatic elevation.
"""
import json
import argparse
import time
from pathlib import Path
from unittest.mock import patch


def menu_close_box(boxes):
    """Recognize the observed DMM icon grid, not a nonexistent menu heading."""
    anchors = {'プロフィール': (115, 447), 'サークル': (606, 447),
               '名簿': (115, 939), '設定': (606, 939)}
    found = set()
    close = []
    for text, score, box in boxes:
        text = text.replace(' ', '')
        x1, y1, x2, y2 = box
        cx, cy = (x1+x2)/2, (y1+y2)/2
        if text in anchors and score >= .8:
            ax, ay = anchors[text]
            if abs(cx-ax) <= 70 and abs(cy-ay) <= 45:
                found.add(text)
        # The translucent X scored .729 on a second real frame; four strong
        # spatial menu anchors remain mandatory independently of this glyph.
        if (score >= .65 and text in ('×', '✕', '✖') and 580 <= x1 < x2 <= 700
                and 1160 <= y1 < y2 <= 1270
                and 20 <= x2-x1 <= 120 and 20 <= y2-y1 <= 110):
            close.append(box)
    return close[0] if found == set(anchors) and len(close) == 1 else None


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
    parser.add_argument('--close-existing', action='store_true', help='Only close an already recognized menu, then verify home')
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
        if not args.close_existing:
            if not home_matches(before, reference):
                raise RuntimeError('Selected Home tab/menu not confirmed; no input sent')
            traced_click(device, window, 653, 1216, root / 'menu-input.json')
            time.sleep(1)
        opened = device.screenshot()
        cv2.imwrite(str(root / 'menu-open-check.png'), opened)
        boxes = ocr_boxes(opened, scale=1)
        (root / 'menu-ocr.json').write_text(json.dumps(boxes, ensure_ascii=False, indent=2), encoding='utf-8')
        close = menu_close_box(boxes)
        if close is None:
            raise RuntimeError('Menu grid and unique X not confirmed; no further input')
        print('DMM menu grid and X confirmed', flush=True)
        x1, y1, x2, y2 = close
        fresh = device.screenshot()
        if fresh.shape != opened.shape or float(np.abs(
                fresh[y1:y2,x1:x2].astype(float)-opened[y1:y2,x1:x2].astype(float)).mean()) > 12:
            raise RuntimeError('Close button changed; left menu open without another click')
        traced_click(device, window, (x1+x2)//2, (y1+y2)//2, root / 'menu-close-input.json')
        time.sleep(1)
        closed = device.screenshot()
        cv2.imwrite(str(root / 'menu-closed-check.png'), closed)
        if not home_matches(closed, reference):
            raise RuntimeError('Close click sent but return to home not confirmed')
        print('DMM menu ' + ('close' if args.close_existing else 'open/close') + ' PASSED; no produce or purchases')
    finally:
        device.stop()


if __name__ == '__main__':
    main()
