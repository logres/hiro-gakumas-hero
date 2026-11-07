"""Internal single-page geometry evidence for a future grouped-list scanner.

No scrolling or cross-page stitching. A region after a heading is an association
candidate, not proof that every card belongs to a complete pile. Public snapshots
continue to use exam_pile_snapshot.read_exam_visible_groups unchanged.
"""
import hashlib

from hiro.vision import deck
from hiro.vision.exam_card_details import is_exam_card_list
from hiro.vision.exam_pile_snapshot import _headings


def _region_evidence(img, region):
    cells, rejected = [], []
    for raw in deck.read_card_grid(img, region, "list"):
        x,y,w,h = raw["rect"]
        if x < region[0] or y < region[1] or x+w > region[2] or y+h > region[3]:
            rejected.append({"rect":list(raw["rect"]),"reason":"cell_crosses_visible_region_boundary"})
            continue
        grade=raw.get("upgrade")
        grade_known=type(grade) is int and grade>=0
        cells.append({"page_cell_index":len(cells),"card_id":raw.get("card_id"),"name":raw.get("name"),
                      "observed_thumbnail_upgrade":grade if grade_known else None,
                      "identity_known":bool(raw.get("card_id")),"thumbnail_grade_known":grade_known,
                      "customized":raw.get("customized"),"rect":[int(x),int(y),int(w),int(h)],
                      "row_in_region":raw.get("row"),"col":raw.get("col"),
                      "crop_sha256":hashlib.sha256(img[y:y+h,x:x+w].tobytes()).hexdigest()})
    return {"cells":cells,"boundary_rejected_cells":rejected,
            "partial_cell_detection":"not_exhaustive/category_mark_reader_only"}


def read_exam_group_page_evidence(img):
    """Return internal complete-cell evidence, including incomplete groups.

    Duplicate physical copies are separate list entries. No-header content is
    unbound; no previous page, historical deck, or inferred group is consulted.
    Cells use xywh; viewport/regions/headings use global xyxy. Row numbers are
    local to this page region, never persistent entity IDs or global pile order.
    Crop hashes bind exact pixels; equal hashes do not merge duplicate entities,
    and moving scenery can change them without changing a card.
    """
    viewport=tuple(deck.LIST_VIEW)
    out={"scope":"current_exam_group_page_evidence","active":False,
         "snapshot_sha256":hashlib.sha256(img.tobytes()).hexdigest(),"viewport":list(viewport),
         "version_basis":"observed_thumbnail_upgrade","draw_order":"unknown",
         "headings":[],"groups":[],"unbound_cells":[],"unbound_regions":[],"problems":[]}
    if not is_exam_card_list(img):
        out["problems"].append("exam_card_list_not_verified")
        return out
    out["active"]=True
    headings=_headings(img)
    out["headings"]=headings
    prefix_end=headings[0]["box"][1] if headings else viewport[3]
    if prefix_end>viewport[1]:
        prefix=(viewport[0],viewport[1],viewport[2],prefix_end)
        evidence=_region_evidence(img,prefix)
        out["unbound_regions"].append({"region":list(prefix),"reason":"no_visible_preceding_heading",**evidence})
        out["unbound_cells"]=evidence["cells"]
    for i,heading in enumerate(headings):
        bottom=headings[i+1]["box"][1] if i+1<len(headings) else viewport[3]
        region=(viewport[0],heading["box"][3],viewport[2],bottom)
        duplicate=sum(h["pile"]==heading["pile"] for h in headings)>1
        evidence=_region_evidence(img,region) if region[1]<region[3] else {"cells":[],"boundary_rejected_cells":[],"partial_cell_detection":"invalid_region"}
        group={"heading_page_index":i,"heading":dict(heading),"expected_group_count":heading["count"],
               "region":list(region),"association_status":"ambiguous_duplicate_heading" if duplicate else "visible_heading_anchor_only",
               "boundaries":{"top":{"kind":"heading_bottom","y":region[1]},
                             "bottom":{"kind":"next_heading_top" if i+1<len(headings) else "viewport_clip","y":bottom}},
               **evidence}
        group["visible_complete_cell_count"]=len(group["cells"])
        if duplicate:group["problem"]="duplicate_group_heading"
        out["groups"].append(group)
    return out

