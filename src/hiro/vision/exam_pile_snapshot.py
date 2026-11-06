"""Pure reader for complete, visible groups in an already-open exam card list.

This is a current-exam snapshot, never the permanent owned deck or draw order.
The caller opts in with HIRO_EXAM_PILE_SNAPSHOT and validates state on closing.
"""
import hashlib
import re

from hiro.vision import deck
from hiro.vision.exam_card_details import is_exam_card_list
from hiro.vision.ocr import ocr_boxes

HEADING_MIN_CONFIDENCE = 0.85

PILE_NAMES = {"手札": "hand", "山札": "draw", "捨札": "grave", "除外": "excluded"}


def _normalize(text):
    return re.sub(r"\s", "", text).replace("（", "(").replace("）", ")")


def _headings(img):
    x1,y1,x2,y2 = deck.LIST_VIEW
    lines = [(t,p,[a+x1,b+y1,c+x1,d+y1])
             for t,p,(a,b,c,d) in ocr_boxes(img[y1:y2,x1:x2])]
    result=[]
    for text,confidence,box in lines:
        normalized=_normalize(text)
        match=re.fullmatch(r"(手札|山札|捨札|除外)(?:\((\d*)\))?",normalized)
        if not match or box[0]>=220:
            continue
        count=int(match[2]) if match[2] and confidence >= HEADING_MIN_CONFIDENCE else None
        if count is None:
            # A narrow exact heading crop recovers split label/count OCR boxes.
            # Two scales must agree, and neither may disagree on the pile label.
            top,bottom=max(y1,box[1]-12),min(y2,box[3]+12)
            candidates=[]
            for scale in (1.0,2.0):
                parts=ocr_boxes(img[top:bottom,25:210],scale=scale)
                joined=_normalize("".join(t for t,_,_ in sorted(parts,key=lambda p:p[2][0])))
                recovered=re.fullmatch(r"(手札|山札|捨札|除外)\((\d+)\)",joined)
                candidates.append(int(recovered[2]) if recovered and recovered[1]==match[1]
                                  and parts and all(p >= HEADING_MIN_CONFIDENCE for _,p,_ in parts) else None)
            if candidates[0] is not None and candidates[0]==candidates[1]:
                count=candidates[0]
        result.append(dict(pile=PILE_NAMES[match[1]],label=match[1],count=count,
                           text=text,confidence=float(confidence),box=box))
    return sorted(result,key=lambda h:h["box"][1])


def read_exam_visible_groups(img):
    """Read exact counts and only publish a group's cards when fully verified.

    Card lists preserve duplicate physical copies. Thumbnail upgrade is observed
    appearance, not the effective hand grade or a verified permanent version.
    No scrolling, device operations, historical inference, or redraw calculation.
    """
    out=dict(scope="current_exam_groups",active=False,draw_order="unknown",groups=[],
             snapshot_sha256=hashlib.sha256(img.tobytes()).hexdigest(),
             version_basis="observed_thumbnail_upgrade",problems=[])
    if not is_exam_card_list(img):
        out["problems"].append("exam_card_list_not_verified")
        return out
    out["active"]=True
    headings=_headings(img)
    for i,heading in enumerate(headings):
        region=(0,heading["box"][3],720,headings[i+1]["box"][1] if i+1<len(headings) else deck.LIST_VIEW[3])
        group=dict(heading,complete=False,region=list(region))
        if sum(h["pile"]==heading["pile"] for h in headings)!=1:
            group["problem"]="duplicate_group_heading"
        elif heading["count"] is None:
            group["problem"]="heading_count_unknown"
        else:
            cells=deck.read_card_grid(img,region,"list")
            cells=[c for c in cells if c["rect"][0]>=region[0] and c["rect"][1]>=region[1]
                   and c["rect"][0]+c["rect"][2]<=region[2] and c["rect"][1]+c["rect"][3]<=region[3]]
            rects=[tuple(c["rect"]) for c in cells]
            if len(cells)!=heading["count"] or len(set(rects))!=len(rects):
                group["problem"]="complete_visible_cell_count_mismatch"
            elif any(not c.get("card_id") or type(c.get("upgrade")) is not int or c["upgrade"] < 0 for c in cells):
                group["problem"]="card_identity_or_thumbnail_upgrade_unknown"
            else:
                group["complete"]=True
                group["cards"]=[dict(card_id=c["card_id"],name=c.get("name"),
                                     observed_thumbnail_upgrade=c["upgrade"],customized=c.get("customized"),
                                     rect=list(c["rect"]),identity_basis="visible_thumbnail") for c in cells]
        out["groups"].append(group)
    return out

