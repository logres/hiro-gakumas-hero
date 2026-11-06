"""Portable integration tests through the same entry points used by the game loop."""
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from hiro import platforms
from hiro.device import connect
from hiro.loop.landscape import LandscapeGuard
import hiro.vision.ocr as recognition
from hiro import real_click


@pytest.fixture(autouse=True)
def providers(monkeypatch):
    platforms.reset()
    for key in platforms.ENV.values():
        monkeypatch.delenv(key, raising=False)
    yield
    platforms.reset()


def test_portable_imports_never_load_os_frameworks():
    code = '''
import sys
import hiro.device, hiro.real_click, hiro.vision.ocr, hiro.loop.landscape
assert not {'Quartz', 'AppKit', 'Vision', 'Foundation'} & set(sys.modules)
assert not any(n.startswith('hiro.platforms.macos.') for n in sys.modules)
'''
    subprocess.run([sys.executable, "-c", code], check=True, env=os.environ.copy())


def test_windows_missing_capabilities_fail_explicitly(monkeypatch):
    monkeypatch.setattr(platforms.sys, "platform", "win32")
    for call in (connect, LandscapeGuard, lambda: recognition.ocr(np.zeros((3, 3, 3))), lambda: real_click.click(1, 2)):
        with pytest.raises(platforms.PlatformUnavailableError, match="Windows/DMM"):
            call()


def test_registered_device_and_window_are_used_by_existing_callers():
    calls = []
    device = SimpleNamespace(screenshot=lambda: np.zeros((1280, 720, 3)), click=lambda x, y: calls.append((x, y)))
    def factory(backend="auto"):
        calls.append(backend)
        return device
    platforms.register("device", SimpleNamespace(connect=factory, real_click=lambda x, y: calls.append(("real", x, y))))
    guard = SimpleNamespace(tick=lambda img, texts: texts == ["recover"], in_live=lambda img: img == "live")
    platforms.register("window", SimpleNamespace(create_guard=lambda: guard, window_bounds=lambda: (1, 2, 720, 1280)))
    assert connect("test") is device
    device.click(20, 30)
    real_click.click(40, 50)
    wrapped = LandscapeGuard()
    assert wrapped.tick(None, ["recover"])
    assert not wrapped.tick(None)
    assert wrapped.in_live("live")
    assert real_click.window_bounds() == (1, 2, 720, 1280)
    assert calls == ["test", (20, 30), ("real", 40, 50)]


def test_ocr_helpers_keep_preprocessing_and_original_box_coordinates():
    calls = []
    def read(img, **kw):
        calls.append((img.shape, kw))
        return [("1,O24", .9)]
    platforms.register("ocr", SimpleNamespace(ocr=read, ocr_boxes=lambda img, **kw: [("文字", .8, (1, 2, 8, 9))]))
    img = np.zeros((10, 20, 3), dtype=np.uint8)
    assert recognition.ocr_int(img) == 1024
    assert recognition.ocr_digits(img) == 1024
    assert calls[-1] == ((34, 44, 3), {"scale": 3.0, "languages": ("en-US",)})
    assert recognition.ocr_batch([img, img], scale=2) == ["1,O24", "1,O24"]
    assert recognition.ocr_boxes(img, scale=4)[0][2] == (1, 2, 8, 9)


def test_environment_factory_and_registration_precedence(monkeypatch):
    instance = object()
    module = SimpleNamespace(build=lambda: instance)
    monkeypatch.setitem(sys.modules, "test_ocr_provider", module)
    monkeypatch.setenv("HIRO_OCR_BACKEND", "test_ocr_provider:build")
    assert platforms.get_backend("ocr") is instance
    replacement = object()
    platforms.register("ocr", replacement)
    assert platforms.get_backend("ocr") is replacement


def test_macos_auto_selects_each_original_implementation_lazily(monkeypatch):
    monkeypatch.setattr(platforms.sys, "platform", "darwin")
    for kind in platforms.ENV:
        provider = object()
        monkeypatch.setitem(sys.modules, f"hiro.platforms.macos.{kind}", provider)
        assert platforms.get_backend(kind) is provider
