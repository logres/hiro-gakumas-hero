"""Exercise the actual kotonebot scaler/device pipeline with a fake native window."""
from types import SimpleNamespace
import sys

import numpy as np
import pytest

pytest.importorskip("kotonebot")
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Requires Windows kotonebot native classes")
from hiro.platforms.windows import device as backend


@pytest.fixture
def native(monkeypatch):
    from kotonebot.client.implements.windows.windows_native import WindowsNativeImpl
    state = SimpleNamespace(size=(360, 640), active=True, stopped=0, clicks=[])
    def activate(window):
        if not state.active:
            raise RuntimeError("Windows refused to activate the selected window")
    monkeypatch.setattr(backend, "activate", activate)
    monkeypatch.setattr(backend, "resolve", lambda: (None, None))
    monkeypatch.setattr(WindowsNativeImpl, "__init__", lambda self, *a, **kw: None)
    monkeypatch.setattr(WindowsNativeImpl, "start", lambda self: None)
    monkeypatch.setattr(WindowsNativeImpl, "stop", lambda self: setattr(state, "stopped", state.stopped+1))
    monkeypatch.setattr(WindowsNativeImpl, "_ensure_active", lambda self: None)
    monkeypatch.setattr(WindowsNativeImpl, "_window", lambda self: SimpleNamespace(
        win32_window=SimpleNamespace(is_active=lambda: state.active)))
    monkeypatch.setattr(WindowsNativeImpl, "screen_size", property(lambda self: state.size))

    def screenshot(self):
        self._ensure_active()
        return np.zeros((state.size[1], state.size[0], 3), dtype=np.uint8)

    def click(self, x, y):
        self._ensure_active()
        state.clicks.append((x, y))

    monkeypatch.setattr(WindowsNativeImpl, "screenshot", screenshot)
    monkeypatch.setattr(WindowsNativeImpl, "click", click)
    return state


def test_normalizes_and_translates_without_global_config(native):
    device = backend.connect()
    try:
        assert device.screenshot().shape == (1280, 720, 3)
        device.click(360, 640)
        assert native.clicks == [(180, 320)]
        native.size = (450, 800)
        with pytest.raises(RuntimeError, match="resized"):
            device.click(360, 640)
        assert device.screenshot().shape == (1280, 720, 3)
        device.click(360, 640)
        assert native.clicks[-1] == (225, 400)
    finally:
        device.stop()
    assert native.stopped == 1


def test_activation_failure_stops_device(native):
    native.active = False
    with pytest.raises(RuntimeError, match="activate"):
        backend.connect()
    assert native.stopped == 1
    assert native.clicks == []


def test_rejects_unknown_mode_before_window_lookup():
    with pytest.raises(ValueError, match="Unsupported"):
        backend.connect("background")


def test_activation_accepts_pywin32_none_success(monkeypatch):
    import sys
    from hiro.platforms.windows.target import activate
    state = {"foreground": 1}
    def set_foreground(hwnd):
        state["foreground"] = hwnd
        return None
    fake = SimpleNamespace(IsIconic=lambda hwnd: False,
                           GetForegroundWindow=lambda: state["foreground"],
                           SetForegroundWindow=set_foreground, error=OSError)
    monkeypatch.setitem(sys.modules, "win32gui", fake)
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(SW_RESTORE=9))
    activate(SimpleNamespace(info=SimpleNamespace(id=2)))
    assert state["foreground"] == 2
