"""No UI: replay home-entry frames and verify bounded, state-gated clicks."""

import importlib.util
import logging
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def guard(monkeypatch):
    clock = NS(now=0.0, frame=None, shots=0)
    clicks = []
    frames = {0: "home"}

    def screenshot():
        clock.frame = frames.get(clock.now, frames[max(t for t in frames if t <= clock.now)])
        clock.shots += 1

    def template(name):
        return NS(exists=lambda: clock.frame == name)

    ongoing = object()
    resource = NS(Produce=NS(
        BoxProduceOngoing=ongoing, BreakProduceDialog=NS(Title=template("discard")),
        ButtonResume=template("resume"), LogoHajime=template("hajime"),
        LogoNia=template("nia"), LogoHif=template("hif"),
    ))
    fake_modules = {
        "kaa.config.const": NS(HifScenario=object),
        "kaa.kaa_context": NS(init_produce_session=lambda *_: None),
        "kaa.tasks": NS(R=resource),
        "kaa.tasks.actions.scenes": NS(at_home=lambda: clock.frame == "home"),
        "kaa.tasks.produce.session": NS(ProduceSession=object),
        "kotonebot": NS(contains=lambda x: x, logging=logging, ocr=NS(find=lambda _: False),
                        device=NS(screenshot=screenshot,
                                  click=lambda *args: clicks.append((clock.now, clock.frame, clock.shots, args)))),
    }
    for name, module in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / "src/hiro/loop/resume.py"
    spec = importlib.util.spec_from_file_location("guard_new_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.active_clock = lambda: clock.now
    mod.time = NS(sleep=lambda seconds: setattr(clock, "now", clock.now + seconds))
    monkeypatch.delenv("HIRO_WINDOWS_HOME_RETRY", raising=False)
    return NS(mod=mod, frames=frames, clicks=clicks, ongoing=ongoing)


def test_default_keeps_one_click(guard):
    with pytest.raises(TimeoutError):
        guard.mod.guard_new(timeout=8)
    assert [c[0] for c in guard.clicks] == [0]


def test_confirmed_home_retries_at_two_seconds_and_stops_at_three(guard, monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    with pytest.raises(TimeoutError):
        guard.mod.guard_new(timeout=12)
    assert [(c[0], c[1]) for c in guard.clicks] == [(0, "home"), (2, "home"), (4, "home")]
    assert len({c[2] for c in guard.clicks}) == 3  # each retry used a fresh screenshot


def test_transient_no_effect_reaches_scenario_after_retry(guard, monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    guard.frames[3] = "hajime"
    guard.mod.guard_new(timeout=8)
    assert [c[0] for c in guard.clicks] == [0, 2]


@pytest.mark.parametrize("state", ["unknown", "dialog"])
def test_unknown_or_dialog_never_retried(guard, monkeypatch, state):
    monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    guard.frames[1] = state
    with pytest.raises(TimeoutError):
        guard.mod.guard_new(timeout=8)
    assert len(guard.clicks) == 1


@pytest.mark.parametrize("state", ["discard", "resume"])
def test_blocking_dialog_takes_precedence_at_retry_boundary(guard, monkeypatch, state):
    monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    guard.frames[2] = state
    # Even an overly permissive home detector cannot override these checks.
    guard.mod.at_home = lambda: True
    with pytest.raises(guard.mod.ResumeBlocked):
        guard.mod.guard_new(timeout=8)
    assert sum(c[3] == (guard.ongoing,) for c in guard.clicks) == 1
    if state == "discard":
        assert guard.clicks[-1][3] == guard.mod.CANCEL_BUTTON


def test_no_retry_at_timeout_boundary(guard, monkeypatch):
    monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    with pytest.raises(TimeoutError):
        guard.mod.guard_new(timeout=2)
    assert len(guard.clicks) == 1


@pytest.mark.parametrize("enabled,normal_home", [(False, False), (True, False), (True, True)])
def test_toolbar_home_is_opt_in_and_normal_home_has_priority(guard, monkeypatch, enabled, normal_home):
    calls = []
    if enabled:
        monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    guard.mod.R.Common = NS(
        ButtonHome=NS(try_click=lambda: calls.append("home") or normal_home),
        ButtonToolbarHome=NS(try_click=lambda: calls.append("toolbar") or True),
    )
    assert guard.mod._try_home_button() == (enabled or normal_home)
    assert calls == (["home", "toolbar"] if enabled and not normal_home else ["home"])


@pytest.mark.parametrize("start_confirm", [False, True])
def test_finish_go_home_uses_recognized_toolbar_without_blind_click(guard, monkeypatch, start_confirm):
    monkeypatch.setenv("HIRO_WINDOWS_HOME_RETRY", "1")
    monkeypatch.setitem(sys.modules, "hiro.loop.assist", NS(Assist=lambda *a, **k: None))
    guard.frames[0] = "produce"
    guard.mod.ocr.ocr = lambda: [NS(text="開始確認")] if start_confirm else []
    matched = []

    def click_toolbar():
        matched.append("toolbar")
        guard.frames[1] = "home"
        return True

    guard.mod.R.Common = NS(
        ButtonHome=NS(try_click=lambda: False),
        ButtonToolbarHome=NS(try_click=click_toolbar),
    )
    assert guard.mod.finish_produce_end(go_home=True, timeout=4)
    assert matched == ["toolbar"]
    assert guard.clicks == []  # must never fall through to the old fixed-coordinate tap
