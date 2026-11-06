"""A wide desktop window must not become an unbounded LIVE wait."""
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("kaa.tasks.R")
from hiro.loop.controller import HiroController


def test_unknown_landscape_stops_without_live_actions(monkeypatch):
    import kotonebot
    stops = []
    guard = SimpleNamespace(tick=lambda img: False, in_live=lambda img: False)
    monkeypatch.setattr(HiroController, "_landscape", guard)
    monkeypatch.setattr(kotonebot, "device", SimpleNamespace(screenshot=lambda: np.zeros((720,1280,3), np.uint8)))
    controller = SimpleNamespace(_landscape=guard,
                                 strategy=SimpleNamespace(_stop=lambda page, why: stops.append(page)))
    HiroController._update(controller)
    assert stops == ["unknown_landscape"]
