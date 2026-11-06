"""A valid but truncated fraction must not short-circuit independent rereading."""

import numpy as np
import pytest

from hiro.vision import action


@pytest.mark.parametrize("native,enlarged,votes,expected", [
    (["2", "/45"], ["2", "2", "/45"], [26, 26, 45, 45], (26, 45)),
    (["2", "/45"], ["2", "2", "/45"], [26, 2, 45, 45], None),
    (["2", "/45"], ["2", "2", "/45"], [None, None, None, None], None),
    (["2/45"], ["2/45"], [], (2, 45)),
    (["26／45"], ["26/45"], [], (26, 45)),
    (["7/45"], ["7／45"], [], (7, 45)),
    (["26"], ["26"], [None, None, None, None], None),
])
def test_fraction_consensus_or_independent_fields(monkeypatch, native, enlarged, votes, expected):
    monkeypatch.setenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", "1")
    monkeypatch.setattr(action, "ocr", lambda img, *, scale, **kw: [(t, .99) for t in (native if scale == 1 else enlarged)])
    reads = iter(votes)
    monkeypatch.setattr(action, "read_dddd", lambda *a: next(reads))
    assert action.read_stamina(np.zeros((1280, 720, 3), dtype=np.uint8)) == expected
