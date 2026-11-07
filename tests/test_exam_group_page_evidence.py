import numpy as np
from hiro.vision import exam_group_page_evidence as reader


def setup(monkeypatch,headings):
    monkeypatch.setattr(reader,"is_exam_card_list",lambda img:True)
    monkeypatch.setattr(reader,"_headings",lambda img:headings)
    return np.zeros((1280,720,3),np.uint8)


def cell(x=48,y=684,cid="same",grade=1):
    return dict(card_id=cid,name=cid,upgrade=grade,customized=False,rect=(x,y,141,141),row=0,col=round((x-48)/161))


def test_incomplete_group_keeps_internal_full_cells_with_boundaries(monkeypatch):
    img=setup(monkeypatch,[dict(pile="draw",count=12,box=[60,633,162,665])])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda img,region,geometry:[cell(),cell(209)] if region[1]==665 else [])
    result=reader.read_exam_group_page_evidence(img)
    group=result["groups"][0]
    assert group["expected_group_count"]==12 and group["visible_complete_cell_count"]==2
    assert [c["col"] for c in group["cells"]]==[0,1]
    assert [c["card_id"] for c in group["cells"]]==["same","same"]
    assert group["boundaries"]["bottom"]=={"kind":"viewport_clip","y":1010}
    assert "complete" not in group and "cards" not in group


def test_occluded_cells_never_become_full_cell_evidence(monkeypatch):
    img=setup(monkeypatch,[dict(pile="grave",count=4,box=[60,847,162,880])])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda img,region,geometry:[cell(y=899)] if region[1]==880 else [])
    group=reader.read_exam_group_page_evidence(img)["groups"][0]
    assert group["cells"]==[] and len(group["boundary_rejected_cells"])==1
    assert group["boundary_rejected_cells"][0]["rect"]==[48,899,141,141]


def test_unknown_identity_and_grade_remain_explicit_internal_unknowns(monkeypatch):
    img=setup(monkeypatch,[dict(pile="draw",count=None,box=[60,633,162,665])])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda img,region,geometry:[cell(cid=None,grade=-1)] if region[1]==665 else [])
    group=reader.read_exam_group_page_evidence(img)["groups"][0]
    c=group["cells"][0]
    assert not c["identity_known"] and not c["thumbnail_grade_known"]
    assert c["observed_thumbnail_upgrade"] is None
    assert group["expected_group_count"] is None


def test_duplicate_headings_keep_separate_page_regions_and_ambiguity(monkeypatch):
    img=setup(monkeypatch,[dict(pile="draw",count=1,box=[60,y,162,y+30]) for y in [420,630]])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a:[])
    result=reader.read_exam_group_page_evidence(img)
    assert [g["heading_page_index"] for g in result["groups"]]==[0,1]
    assert all(g["association_status"]=="ambiguous_duplicate_heading" for g in result["groups"])
    assert result["groups"][0]["boundaries"]["bottom"]["kind"]=="next_heading_top"


def test_no_header_keeps_orphan_cells_unbound(monkeypatch):
    img=setup(monkeypatch,[])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda *a:[cell(y=469)])
    result=reader.read_exam_group_page_evidence(img)
    assert result["groups"]==[] and len(result["unbound_cells"])==1
    assert "pile" not in result["unbound_cells"][0]
    assert result["unbound_regions"][0]["reason"]=="no_visible_preceding_heading"


def test_cards_above_first_heading_are_not_assigned_to_that_group(monkeypatch):
    img=setup(monkeypatch,[dict(pile="grave",count=1,box=[60,633,162,665])])
    monkeypatch.setattr(reader.deck,"read_card_grid",lambda img,region,geometry:[cell(y=469)] if region[1]==395 else [cell()])
    result=reader.read_exam_group_page_evidence(img)
    assert result["unbound_cells"][0]["rect"][1]==469
    assert result["groups"][0]["cells"][0]["rect"][1]==684
