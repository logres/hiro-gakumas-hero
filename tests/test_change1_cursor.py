"""Four-corner support avoids adjacent select-change cursor bleed."""
import cv2
import numpy as np
import pytest
from hiro.vision.deck import _change1_selected

CANDIDATES=[{"index":i,"center":[x,899]} for i,x in enumerate((223,361,500))]


def corners(img,index,which=range(4)):
    x=CANDIDATES[index]["center"][0]-62; y=837; n=124;e=16;size=30
    boxes=((x-e,y-e),(x+n+e-size,y-e),(x-e,y+n+e-size),(x+n+e-size,y+n+e-size))
    for k in which:
        a,b=boxes[k]
        img[b+5:b+20,a+5:a+25]=(0,150,255)

@pytest.mark.parametrize("index",range(3))
def test_each_column_requires_its_own_four_corners(index):
    img=np.zeros((1280,720,3),np.uint8)
    corners(img,index)
    assert _change1_selected(img,CANDIDATES)==index

@pytest.mark.parametrize("which",[[],[0],[0,1],[0,1,2]])
def test_partial_corner_or_illustration_is_not_selection(which):
    img=np.zeros((1280,720,3),np.uint8)
    corners(img,2,which)
    assert _change1_selected(img,CANDIDATES) is None

def test_two_actual_selected_cursors_remain_unknown():
    img=np.zeros((1280,720,3),np.uint8)
    corners(img,0);corners(img,2)
    assert _change1_selected(img,CANDIDATES) is None
