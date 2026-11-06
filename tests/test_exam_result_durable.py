from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize("passed", [True, False])
def test_result_is_recorded_before_exit_or_retry_navigation(monkeypatch, passed):
    import hiro.produce.hif as hif
    import hiro.vision.hif as vision

    calls = []
    obj = object.__new__(hif.HiroHifStrategy)
    obj.rec = NS(log=lambda *a, **kw: None)
    obj.s = NS(observe=lambda **kw: calls.append(("observe", kw["fields"])),
               record=lambda: calls.append(("record", None)), note=lambda *a: None)
    obj._require_deck_review = lambda reason: calls.append(("pending", None))
    monkeypatch.setattr(hif, "device", NS(screenshot=lambda: object()))
    monkeypatch.setattr(vision, "is_hif_result", lambda img: True)
    monkeypatch.setattr(vision, "read_hif_result", lambda img: {"passed": passed, "score": 81031})
    monkeypatch.setattr(hif, "ocr", NS(ocr=lambda: calls.append(("navigation", None)) or []))
    assert obj._retry_if_failed("qualify-3") is False
    assert calls[:3] == [("observe", {"passed": passed, "score": 81031}),
                         ("pending", None), ("record", None)]
    assert [c[0] for c in calls[3:]] == ([] if passed else ["navigation"])
