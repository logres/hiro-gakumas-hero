"""Capture the selected Windows game through Hiro, without clicking.

Run from the repository root. Capturing activates the window. Screenshots and
OCR stay in the ignored reports directory by default; do not commit them.
"""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('reports/windows-probe'))
    args = parser.parse_args()
    import cv2
    from hiro.platforms.windows.device import connect
    from hiro.platforms.windows.ocr import ocr_boxes
    from hiro.platforms.windows.window import create_guard
    from hiro.platforms.windows.target import integrity_level, resolve

    window, _ = resolve()
    permissions = {'hiro': integrity_level(os.getpid()), 'game': integrity_level(window.info.process_id)}
    device = connect()
    try:
        raw = device.screenshot_raw()
        logical = device.scaler.transform_screenshot(raw)
        boxes = ocr_boxes(logical, scale=1)
        report = {
            'physical_shape': list(raw.shape), 'logical_shape': list(logical.shape),
            'live_cue': create_guard().in_live(logical),
            'ocr': [{'text': text, 'confidence': confidence, 'box': list(box)}
                    for text, confidence, box in boxes],
            'input_sent': False,
            'integrity_levels': permissions,
            'input_integrity_compatible': permissions['hiro'] >= permissions['game'],
        }
        args.output.mkdir(parents=True, exist_ok=True)
        for name, frame in [('physical.png', raw), ('logical.png', logical)]:
            if not cv2.imwrite(str(args.output / name), frame):
                raise RuntimeError(f'Could not save {name}')
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'physical_shape': report['physical_shape'],
                          'logical_shape': report['logical_shape'], 'ocr_regions': len(boxes),
                          'live_cue': report['live_cue'], 'input_sent': False,
                          'integrity_levels': permissions,
                          'input_integrity_compatible': report['input_integrity_compatible'],
                          'report': str((args.output / 'report.json').resolve())}))
    finally:
        device.stop()


if __name__ == '__main__':
    main()
