from copy import deepcopy

from hiro.produce.guidance_grid import locate_guidance_card, scan_guidance_grid


def card(cid, row, col=0, **extra):
    return dict(card_id=cid, upgrade=0, row=row, col=col, index=row*4+col,
                available=True, customized=False, center=[100, 700+row*100],
                customizations=[{"id": "offer"}], **extra)


class Grid:
    def __init__(self, pages):
        self.pages, self.pos = pages, len(pages)-1
        self.swipes = []
    def shoot(self):
        return self.pos
    def read(self, image):
        return dict(view="select", cards=deepcopy(self.pages[image]),
                    at_top=image == 0, at_bottom=image == len(self.pages)-1,
                    scrollable=len(self.pages)>1)
    def swipe(self, x1, y1, x2, y2):
        self.swipes.append((x1,y1,x2,y2))
        self.pos = min(len(self.pages)-1, self.pos+1) if y1>y2 else max(0,self.pos-1)
    def args(self):
        return dict(shoot=self.shoot, read=self.read, swipe=self.swipe, wait=lambda _: None)


def pages():
    return [[card(str(r*4+c), r, c) for r in range(2) for c in range(4)],
            [card(str((r+1)*4+c), r, c) for r in range(2) for c in range(4)]]


def test_full_scan_preserves_metadata_without_stale_coordinates():
    g = Grid(pages())
    result = scan_guidance_grid(**g.args())
    assert result["complete"] and result["returned_to_top"] and g.pos == 0
    assert len(result["cards"]) == 12
    assert all("center" not in c and "row" not in c and "index" not in c for c in result["cards"])
    assert result["cards"][-1]["customizations"] == [{"id": "offer"}]
    assert result["cards"][-1]["screen_index"] == 1
    assert result["cards"][-1]["screen_local_index"] == 7


def test_missing_bottom_is_never_complete_and_restores_top():
    g = Grid(pages())
    original = g.read
    g.read = lambda i: {**original(i), "at_bottom": None}
    result = scan_guidance_grid(**g.args(), max_scrolls=2)
    assert not result["complete"] and g.pos == 0
    assert "final_bottom_unverified_or_scroll_limit" in result["problems"]


def test_unknown_is_reported():
    p = pages()
    p[0][0]["card_id"] = None
    result = scan_guidance_grid(**Grid(p).args())
    assert not result["complete"]
    assert result["unknown_observations"] == [{"screen_index": 0, "screen_local_index": 0}]


def test_fresh_locate_scrolls_to_target():
    g = Grid(pages())
    scan = scan_guidance_grid(**g.args())
    target = locate_guidance_card("11", 0, scan=scan, **g.args())
    assert g.pos == 1 and target["center"] == [100,800] and target["index"] == 7


def test_duplicate_identity_never_gets_an_arbitrary_location():
    p = pages()
    p[1][-1]["card_id"] = "0"
    g = Grid(p)
    assert locate_guidance_card("0", 0, **g.args()) is None
    assert g.pos == 0


def test_error_still_restores_top():
    g = Grid(pages())
    original = g.read
    reads = 0
    def read(i):
        nonlocal reads
        reads += 1
        if reads == 3:
            raise RuntimeError("OCR failed")
        return original(i)
    g.read = read
    import pytest
    with pytest.raises(RuntimeError, match="OCR failed"):
        scan_guidance_grid(**g.args())
    assert g.pos == 0



def test_repeated_row_overlap_is_not_instance_evidence():
    repeated = [card(str(c), r, c) for r in range(2) for c in range(4)]
    g = Grid([repeated, repeated])
    result = scan_guidance_grid(**g.args())
    assert not result["complete"]
    assert "ambiguous_row_overlap" in result["problems"]


def test_unavailable_target_is_not_located():
    p = pages()
    p[1][-1]["available"] = False
    g = Grid(p)
    assert locate_guidance_card("11", 0, **g.args()) is None


def test_top_must_be_verified():
    g = Grid(pages())
    original = g.read
    g.read = lambda i: {**original(i), "at_top": None}
    result = scan_guidance_grid(**g.args(), max_scrolls=2)
    assert not result["complete"]
    assert "initial_top_unverified" in result["problems"]
    assert "return_top_unverified" in result["problems"]


def test_guidance_geometry_preserves_full_row_overlap():
    from hiro.produce.guidance_grid import SCROLL_REGION, SCROLL_X
    from hiro.vision.customize import SCROLL_REGION as VISION_REGION
    from hiro.vision.deck import dialog_scroll
    import numpy as np
    assert SCROLL_REGION == VISION_REGION == (0, 625, 720, 988)
    image = np.zeros((1280,720,3), dtype=np.uint8)
    image[821:975, SCROLL_X] = 255
    assert dialog_scroll(image, SCROLL_REGION, SCROLL_X)["at_bottom"] is True
    assert dialog_scroll(image, (0,625,720,1000), SCROLL_X)["at_bottom"] is False
    g = Grid(pages())
    scan_guidance_grid(**g.args())
    assert all(abs(y1-y2) == 120 for _, y1, _, y2 in g.swipes)
