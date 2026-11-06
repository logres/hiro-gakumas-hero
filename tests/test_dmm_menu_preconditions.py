"""The shared menu icon alone cannot establish the selected home page."""
import importlib.util
from pathlib import Path

import numpy as np


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
