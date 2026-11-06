"""Foreground handoff detaches even when activation remains refused."""
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('refuse', [False, True])
def test_foreground_handoff_cleanup(monkeypatch, refuse):
    from hiro.platforms.windows.target import activate
    state = {'foreground': 9, 'attached': False}
    events = []

    def attach(current, foreground, enabled):
        events.append((current, foreground, enabled))
        state['attached'] = enabled

    def set_foreground(hwnd):
        if not state['attached'] or refuse:
            raise OSError('foreground lock')
        state['foreground'] = hwnd

    monkeypatch.setitem(sys.modules, 'win32gui', SimpleNamespace(
        IsIconic=lambda hwnd: False, GetForegroundWindow=lambda: state['foreground'],
        SetForegroundWindow=set_foreground, error=OSError))
    monkeypatch.setitem(sys.modules, 'win32con', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'win32api', SimpleNamespace(GetCurrentThreadId=lambda: 1))
    monkeypatch.setitem(sys.modules, 'win32process', SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (2, 3), AttachThreadInput=attach))
    window = SimpleNamespace(info=SimpleNamespace(id=7))
    if refuse:
        with pytest.raises(RuntimeError, match='refused'):
            activate(window)
    else:
        activate(window)
        assert state['foreground'] == 7
    assert events == [(1, 2, True), (1, 2, False)]
    assert state['attached'] is False
