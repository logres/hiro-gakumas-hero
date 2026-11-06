"""The shared menu icon alone cannot establish the selected home page."""
import importlib.util
from pathlib import Path

import numpy as np


def test_real_menu_without_heading_or_close_text():
    spec = importlib.util.spec_from_file_location('dmm_menu_check', Path(__file__).parents[1]/'tools/check_dmm_menu.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Non-personal OCR coordinates from the real DMM menu regression.
    boxes = [('プロフィール', .99, [54,432,176,461]),
             ('サークル', .99, [564,432,648,461]),
             ('名簿', .99, [92,926,138,952]),
             ('設定', .99, [584,926,629,952]),
             ('×', .91, [592,1182,677,1250])]
    assert module.menu_close_box(boxes) == boxes[-1][2]
    assert module.menu_close_box(boxes[:-1]) is None
    assert module.menu_close_box(boxes[1:]) is None
    assert module.menu_close_box(boxes + [boxes[-1]]) is None
    assert module.menu_close_box(boxes[:-1] + [('×', .4, boxes[-1][2])]) is None
    assert module.menu_close_box(boxes[:-1] + [('×', .99, [20,20,80,80])]) is None


def test_other_tab_with_same_menu_is_rejected():
    spec = importlib.util.spec_from_file_location('dmm_menu_check', Path(__file__).parents[1]/'tools/check_dmm_menu.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = np.zeros((1280,720,3), dtype=np.uint8)
    home[1180:1260,610:700] = 80
    home[1125:1208,325:395] = (20,100,240)
    other_tab = home.copy()
    other_tab[1125:1208,325:395] = (80,40,20)
    assert module.home_matches(home,home)
    assert not module.home_matches(other_tab,home)
    assert not module.home_matches(home[:720],home)
