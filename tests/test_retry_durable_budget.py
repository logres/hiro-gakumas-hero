import json
from types import SimpleNamespace as NS

import pytest

import hiro.produce.hif as hif


def strategy(path):
    result = hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    notes = []
    result.s = NS(trace=NS(dir=path), notes=notes, note=notes.append)
    return result


def box(text, y=1100):
    return NS(text=text, rect=NS(center=NS(x=300, y=y)))


def fake_clock(monkeypatch):
    clock = NS(now=0)
    monkeypatch.setattr(hif, "time", NS(monotonic=lambda: clock.now, time=lambda: clock.now))
    monkeypatch.setattr(hif, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))


def test_disabled_retry_never_becomes_free_and_budget_survives_three_resumes(tmp_path, monkeypatch):
    fake_clock(monkeypatch)
    clicks = []
    result = [box("敗退", 300), box("再挑戦")]
    monkeypatch.setattr(hif, "ocr", NS(ocr=lambda: result))

    def click(rect):
        # Reservation is already on disk when the first input is dispatched.
        events = [json.loads(l) for l in (tmp_path / "run/retry-budget.jsonl").read_text(encoding="utf-8").splitlines()]
        assert events[-1]["event"] == "retry_reserved"
        assert events[-1]["used"] == len(clicks) + 1
        clicks.append(rect)

    monkeypatch.setattr(hif, "device", NS(click=click, screenshot=lambda: None))
    for attempt in range(1, 5):
        current = strategy(tmp_path / f"run-r{attempt}")
        assert current._click_retry("qualify-1", result[-1], [box("本日あと1回無料")]) is None
        assert current._retries_so_far("qualify-1") == min(attempt, 3)
        assert not any("使用再挑戦" in note or "用了免费" in note for note in current.s.notes)
    assert len(clicks) == 3


def test_click_error_is_durable_even_without_trace_record(tmp_path, monkeypatch):
    current = strategy(tmp_path / "run-r1")
    monkeypatch.setattr(hif, "device", NS(click=lambda rect: (_ for _ in ()).throw(RuntimeError("unknown input result"))))
    with pytest.raises(RuntimeError, match="unknown input result"):
        current._click_retry("qualify-1", box("再挑戦"), [])
    assert strategy(tmp_path / "run-r2")._retries_so_far("qualify-1") == 1


def test_historical_notes_and_reservations_are_not_added_twice(tmp_path):
    for segment in ("run", "run-r1"):
        directory = tmp_path / segment
        directory.mkdir()
        (directory / "steps.jsonl").write_text(json.dumps({"notes": ["qualify-1 敗退，使用再挑戦（ticket）"]}) + "\n", encoding="utf-8")
    current = strategy(tmp_path / "run-r2")
    assert current._retries_so_far("qualify-1") == 2
    current._reserve_retry("qualify-1", 2)
    current.s.notes.append("qualify-1 敗退，使用再挑戦（free）")
    assert current._retries_so_far("qualify-1") == 3
    assert strategy(tmp_path / "run-r3")._retries_so_far("qualify-1") == 3
    assert current._retries_so_far("qualify-2") == 0


def test_verified_historical_floor_and_corrupt_budget_fail_closed(tmp_path):
    current = strategy(tmp_path / "run-r8")
    path = current._retry_budget_path()
    path.parent.mkdir()
    path.write_text(json.dumps({"event": "retry_budget_floor", "label": "qualify-1", "used": 3,
                                "evidence": "two trace notes plus third confirmed ticket decrement in log"}) + "\n", encoding="utf-8")
    assert current._retries_so_far("qualify-1") == 3
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"event":"retry_reserved"')
    assert current._retries_so_far("qualify-1") == 3


def test_unclosed_confirmation_is_not_success(tmp_path, monkeypatch):
    fake_clock(monkeypatch)
    current = strategy(tmp_path / "run")
    clicks = []
    dialog = [box("再挑戦確認", 400), box("本日あと1回無料", 950), box("決定")]
    monkeypatch.setattr(hif, "ocr", NS(ocr=lambda: dialog))
    monkeypatch.setattr(hif, "device", NS(click=clicks.append, screenshot=lambda: None))
    assert current._click_retry("qualify-1", box("再挑戦"), []) is None
    assert len(clicks) == 1 + current.RETRY_CONFIRM_TAPS
    assert current._retries_so_far("qualify-1") == 1


def test_failed_durable_write_prevents_input(tmp_path, monkeypatch):
    import os
    current = strategy(tmp_path / "run")
    monkeypatch.setattr(os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk error")))
    monkeypatch.setattr(hif, "device", NS(click=lambda rect: pytest.fail("No input without durable reservation")))
    with pytest.raises(OSError, match="disk error"):
        current._click_retry("qualify-1", box("再挑戦"), [])
