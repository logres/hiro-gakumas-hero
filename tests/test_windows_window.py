from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hiro.platforms.windows import window


def test_tick_never_loads_or_controls_device(monkeypatch):
    monkeypatch.setattr(window, '_live_matcher', lambda: pytest.fail('tick loaded matcher'))
    assert window.create_guard() is not window.create_guard()
    assert window.create_guard().tick(None, ['anything']) is False


def test_bounds_resolves_target_without_activation(monkeypatch):
    pytest.importorskip('kotonebot')
    from kotonebot.primitives import Rect
    from hiro.platforms.windows import target
    fake = SimpleNamespace(get_bounds=lambda: Rect(-20, 40, 800, 600))
    monkeypatch.setattr(target, 'resolve', lambda: (fake, None))
    assert window.window_bounds() == (-20, 40, 800, 600)


def test_missing_dependencies_are_not_no_text(monkeypatch):
    from hiro.platforms import PlatformUnavailableError
    def missing():
        raise PlatformUnavailableError('missing assets')
    monkeypatch.setattr(window, '_live_matcher', missing)
    with pytest.raises(PlatformUnavailableError):
        window.create_guard().in_live(np.zeros((720, 1280, 3), np.uint8))


@pytest.mark.upstream_assets
def test_existing_upstream_live_frames_and_negatives(monkeypatch):
    cv2 = pytest.importorskip('cv2')
    pytest.importorskip('kotonebot')
    pytest.importorskip('kaa')
    base = Path(__file__).resolve().parents[1] / 'vendor/kaa/kotonebot-resource/sprites/jp/produce'
    if not (base / 'screenshot_produce_end.png').is_file():
        pytest.skip('Initialize KAA submodule for upstream screenshot validation')
    # The pure matching API must not obtain a screenshot or send input.
    from kotonebot.client.device import Device
    monkeypatch.setattr(Device, 'screenshot', lambda *a, **k: pytest.fail('unexpected screenshot'))
    monkeypatch.setattr(Device, 'click', lambda *a, **k: pytest.fail('unexpected click'))
    guard = window.create_guard()
    live = cv2.imread(str(base / 'screenshot_produce_end.png'))
    assert guard.in_live(live)
    assert guard.in_live(cv2.resize(live, (640, 360)))
    # Confirmation is not an active performance; controller policy decides how to stop/dispatch it.
    assert not guard.in_live(cv2.imread(str(base / 'screenshot_produce_end_skip.png')))
    assert not guard.in_live(np.zeros((720, 1280, 3), np.uint8))
    assert not guard.in_live(np.full((720, 1280, 3), 255, np.uint8))
    assert not guard.in_live(np.random.default_rng(42).integers(0, 256, (720, 1280, 3), dtype=np.uint8))
    assert not guard.in_live(np.zeros((1280, 720, 3), np.uint8))
    assert not guard.in_live(cv2.resize(live, (1000, 720)))
    assert not guard.in_live(None)
