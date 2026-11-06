"""Snapshot-bound card detail evidence, independent of catalog CardView fields.

The recognition layer supplies a hash of the actual exam snapshot and explicit
selected/detail identities. This validates their binding, not OCR correctness.
Paths, preview effects and caller-supplied semantic claims are never promoted.
"""

import json
import re


def _identity(value):
    if not isinstance(value, dict):
        return None
    slot, cid, up = (value.get(k) for k in ("slot", "card_id", "upgrade"))
    if (type(slot) is not int or slot < 0 or not isinstance(cid, str)
            or not cid.strip() or type(up) is not int or up < 0):
        return None
    return slot, cid, up


def card_effect_context(hand, evidence=None, *, snapshot_sha256):
    """Return only exact current hand/detail bindings; absence is optional.

    ``evidence`` is a list of records with snapshot_sha256, slot/card_id/upgrade,
    selection_verified=True, selected_card and detail_card (each carrying the
    same slot/card_id/upgrade), and raw_ocr_lines (list[str]). The hash must be
    computed by the caller from the current snapshot, never loaded from a path
    supplied by a record. A new frame/action requires a new snapshot binding.
    Duplicate records for a slot or same-version hand copies are rejected rather
    than arbitrarily selected. Optional detail_sha256 identifies the detail image.
    """
    result = {"cards": [], "note": "详情 OCR 是本帧原始局部证据，可能缺字或漏行；"
              "未验证完整效果、费用、条件或语义，不替代 CardView 主数据字段。"}
    if (not isinstance(snapshot_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256) is None
            or not isinstance(evidence, list)):
        return result
    identities = [_identity({k: getattr(card, k, None) for k in ("slot", "card_id", "upgrade")})
                  for card in hand]
    slots = [identity[0] for identity in identities if identity is not None]
    versions = [identity[1:] for identity in identities if identity is not None]
    record_slots = [record.get("slot") for record in evidence if isinstance(record, dict)]
    for record in evidence:
        identity = _identity(record)
        if (identity is None or identities.count(identity) != 1
                or slots.count(identity[0]) != 1 or record_slots.count(identity[0]) != 1
                or versions.count(identity[1:]) != 1
                or record.get("snapshot_sha256") != snapshot_sha256
                or record.get("selection_verified") is not True
                or _identity(record.get("selected_card")) != identity
                or _identity(record.get("detail_card")) != identity):
            continue
        lines = record.get("raw_ocr_lines")
        if not isinstance(lines, list) or not lines or any(not isinstance(line, str) for line in lines):
            continue
        if not any(line.strip() for line in lines):
            continue
        detail_hash = record.get("detail_sha256")
        if detail_hash is not None and (not isinstance(detail_hash, str)
                                       or re.fullmatch(r"[0-9a-f]{64}", detail_hash) is None):
            continue
        result["cards"].append({
            "slot": identity[0], "card_id": identity[1], "upgrade": identity[2],
            "snapshot_sha256": snapshot_sha256, "evidence_source": "selected_exam_card_detail",
            "raw_ocr_lines": list(lines), "ocr_completeness": "partial",
            "semantic_facts": [], "actual_effects_status": "unknown",
            "customization_effects_known": False,
            **({"detail_sha256": detail_hash} if detail_hash is not None else {}),
        })
    return result


def attach_card_effect_context(public_info, hand, evidence=None, *, snapshot_sha256):
    """Append validated evidence to the public_info frozen by exam trace replay."""
    context = card_effect_context(hand, evidence, snapshot_sha256=snapshot_sha256)
    if not context["cards"]:
        return public_info
    text = "本帧卡牌详情原始证据：" + json.dumps(context, ensure_ascii=False)
    return "\n".join(part for part in (public_info, text) if part)
