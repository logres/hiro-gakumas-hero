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
    from hiro.vision import digits
    monkeypatch.setattr(digits, "read_number", lambda *args, **kwargs: None)
    result = items.read_pitems(image)
    assert len(result) == 1
    assert result[0]["asset"] == "observed-icon"
    assert result[0]["remaining_charges"] is None
    assert items.read_pitems(np.zeros_like(image)) == []
    # Enabling the candidate layout still accepts the original layout.
    old_image = np.zeros_like(image)
    old_image[old_y, x] = 255
    assert len(items.read_pitems(old_image)) == 1
    # Competing layouts are not combined into duplicate physical items.
    old_image[old_y - items.PITEM_PITCH - 1, x] = 255
    assert len(items.read_pitems(old_image)) == 2


def test_shifted_match_still_rejects_ambiguous_templates(monkeypatch):
    monkeypatch.setenv("HIRO_PITEM_COMPACT_HUD", "1")
    monkeypatch.setattr(items, "_library", lambda *a: SimpleNamespace(
        match_many=lambda crops: [[(.8, "one"), (.75, "two")] for _ in crops], names={}))
    assert items.read_pitems(np.zeros((1280, 720, 3), dtype=np.uint8)) == []


def test_two_rows_keep_identity_and_geometry_bound_counts_even_if_upper_weaker(monkeypatch):
    from hiro.vision import digits
    monkeypatch.setenv("HIRO_PITEM_COMPACT_HUD", "1")
    image = np.zeros((1280,720,3), np.uint8)
    x,y = items.PITEM_TOP_LEFT
    image[y-70,x] = 100
    image[y,x] = 200
    def match(crops):
        return [[(.65 if c[0,0,0] == 100 else .95, "upper" if c[0,0,0] == 100 else "lower"),(.1,"other")]
                if c[0,0,0] else [(.2,"noise"),(.1,"other")] for c in crops]
    monkeypatch.setattr(items, "_library", lambda *a: SimpleNamespace(match_many=match,names={}))
    monkeypatch.setattr(digits,"read_number",lambda img,box: {228:1,298:2}[box[1]])
    out=items.read_pitems(image)
    assert [(v["slot"],v["asset"],v["remaining_charges"]) for v in out] == [(0,"upper",1),(1,"lower",2)]
    assert out[0]["charges_box"] == [683,228,715,256]
    assert out[1]["charges_box"] == [683,298,715,326]


def test_cache_includes_badge_top_and_right_edge(monkeypatch):
    from hiro.vision.region_cache import RegionCache
    monkeypatch.setenv("HIRO_PITEM_COMPACT_HUD", "1")
    image=np.zeros((1280,720,3),np.uint8)
    calls=[]
    monkeypatch.setattr(items,"_read_pitems",lambda img: calls.append(1) or [{"remaining_charges":int(img[230,710,0])}])
    cache=RegionCache()
    assert items.read_pitems(image,cache=cache)[0]["remaining_charges"] == 0
    image[228:234,708:714] = 255
    assert items.read_pitems(image,cache=cache)[0]["remaining_charges"] == 255
    assert len(calls)==2
