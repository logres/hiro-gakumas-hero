"""Opt-in item row shift; matching still needs image evidence and confidence."""

from types import SimpleNamespace

import numpy as np

from hiro.vision import items


def test_compact_layout_is_opt_in_and_never_infers_item_from_identity(monkeypatch):
    monkeypatch.delenv("HIRO_PITEM_COMPACT_HUD", raising=False)
    image = np.zeros((1280, 720, 3), dtype=np.uint8)
    # Synthetic exact alignment marker one row above legacy origin, with -1px
    # rendering offset as seen in the Windows frame. It is not a game asset.
    x, old_y = items.PITEM_TOP_LEFT
    image[old_y - items.PITEM_PITCH - 1, x] = 255

    def match(crops):
        return [[(.8, "observed-icon"), (.2, "other")] if crop[0, 0, 0] == 255
                else [(.2, "other"), (.1, "observed-icon")] for crop in crops]

    monkeypatch.setattr(items, "_library", lambda *a: SimpleNamespace(match_many=match, names={"observed-icon": "Synthetic item"}))
    assert items.read_pitems(image) == []
    monkeypatch.setenv("HIRO_PITEM_COMPACT_HUD", "1")
    assert items.read_pitems(image) == [{"slot": 0, "asset": "observed-icon", "name": "Synthetic item", "score": .8, "margin": .6}]
    assert items.read_pitems(np.zeros_like(image)) == []
    # Enabling the candidate layout still accepts the original layout.
    old_image = np.zeros_like(image)
    old_image[old_y, x] = 255
    assert len(items.read_pitems(old_image)) == 1
    # Competing layouts are not combined into duplicate physical items.
    old_image[old_y - items.PITEM_PITCH - 1, x] = 255
    assert len(items.read_pitems(old_image)) == 1


def test_shifted_match_still_rejects_ambiguous_templates(monkeypatch):
    monkeypatch.setenv("HIRO_PITEM_COMPACT_HUD", "1")
    monkeypatch.setattr(items, "_library", lambda *a: SimpleNamespace(
        match_many=lambda crops: [[(.8, "one"), (.75, "two")] for _ in crops], names={}))
    assert items.read_pitems(np.zeros((1280, 720, 3), dtype=np.uint8)) == []
