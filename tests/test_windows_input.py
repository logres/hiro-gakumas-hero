import ctypes
from types import SimpleNamespace

import pytest

from hiro.platforms.windows import input as native


def test_windows_input_abi_and_packets():
    assert ctypes.sizeof(native.MOUSEINPUT) == (32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24)
    assert ctypes.sizeof(native.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    packets = native._click_packets(2559, 1599, (0, 0, 2560, 1600))
    assert [p.type for p in packets] == [0, 0, 0]
    assert [p.mi.dwFlags for p in packets] == [0xC001, 2, 4]
    assert (packets[0].mi.dx, packets[0].mi.dy) == (65535, 65535)
    assert all(p.mi.mouseData == p.mi.time == p.mi.dwExtraInfo == 0 for p in packets)


def test_negative_monitor_origin_and_midpoint():
    assert native._normalize(-1920, -100, (-1920, -100, 3841, 1601)) == (0, 0)
    assert native._normalize(0, 700, (-1920, -100, 3841, 1601)) == (32768, 32768)
    assert native._normalize(1920, 1500, (-1920, -100, 3841, 1601)) == (65535, 65535)


@pytest.mark.parametrize('x,y,bounds', [(-1, 0, (0, 0, 10, 10)), (10, 0, (0, 0, 10, 10)),
    (0, 10, (0, 0, 10, 10)), (0, 0, (0, 0, 1, 10)), (0.5, 0, (0, 0, 10, 10))])
def test_invalid_coordinates(x, y, bounds):
    with pytest.raises(ValueError):
        native._click_packets(x, y, bounds)


@pytest.mark.parametrize('accepted,release_result', [(3, 1), (0, 1), (1, 1), (2, 1), (2, 0)])
def test_checked_insertion_and_release_cleanup(monkeypatch, accepted, release_result):
    calls = []
    def send(count, packets, size):
        calls.append((count, [p.mi.dwFlags for p in packets], size))
        return accepted if len(calls) == 1 else release_result
    fake = SimpleNamespace(GetSystemMetrics=lambda i: {76: 0, 77: 0, 78: 2560, 79: 1600}[i], SendInput=send)
    monkeypatch.setattr(native, '_api', lambda: fake)
    if accepted == 3:
        native.click_screen(825, 1364)
    else:
        with pytest.raises(RuntimeError, match=f'accepted {accepted}/3') as error:
            native.click_screen(825, 1364)
        if accepted == 2:
            assert f'cleanup accepted {release_result}/1' in str(error.value)
    assert calls[0] == (3, [0xC001, 2, 4], ctypes.sizeof(native.INPUT))
    assert len(calls) == (2 if accepted == 2 else 1)
    if accepted == 2:
        assert calls[1] == (1, [4], ctypes.sizeof(native.INPUT))
