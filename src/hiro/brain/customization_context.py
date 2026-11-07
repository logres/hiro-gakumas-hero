"""Executed customization evidence, never a reconstructed actual card definition."""
import copy
import os
import sqlite3
from hiro.state.catalog import CatalogUnavailable

FLAG = "HIRO_CUSTOMIZATION_TRANSFORM_CONTEXT"


def enabled():
    return os.environ.get(FLAG) == "1"


def inherit_review(previous, reviewed):
    """Only unique exact copies with a still-observed customization can inherit."""
    for card in reviewed:
        key = (card.get("card_id"), card.get("upgrade"))
        if not key[0] or type(key[1]) is not int or key[1] < 0:
            continue
        old = [c for c in previous if (c.get("card_id"), c.get("upgrade")) == key]
        new = [c for c in reviewed if (c.get("card_id"), c.get("upgrade")) == key]
        if len(old) == len(new) == 1 and card.get("customized") is True:
            if "customization_history" in old[0]:
                card["customization_history"] = copy.deepcopy(old[0]["customization_history"])


def transformation_context(card, master):
    result = {"actual_effects_status": "unknown", "customization_effects_known": False,
              "history_completeness": "unknown", "executed_customizations": [],
              "note": "执行ID只说明已确认的本次购买，不证明历史完整。各层候选互斥，不相加、不默认最高层；grow_effects为原始主数据变换，不是已应用后的实际效果全文。"}
    for event in card.get("customization_history") or []:
        entry = copy.deepcopy(event)
        entry.update(count_status="unknown", candidate_transformations=[])
        try:
            base = master.card(card["card_id"], card["upgrade"])
            cid = event.get("customize_id")
            allowed = base.get("produceCardCustomizeIds")
            if not isinstance(allowed, list) or not cid or cid not in allowed:
                raise KeyError("customization not allowed by exact version")
            rows = master.by_id("ProduceCardCustomize", cid)
            if not rows:
                raise KeyError(cid)
            for row in rows:
                grow_ids = row.get("produceCardGrowEffectIds")
                if not isinstance(grow_ids, list) or not grow_ids:
                    raise KeyError("missing transformation")
                effects = [master.one("ProduceCardGrowEffect", gid) for gid in grow_ids]
                entry["candidate_transformations"].append({
                    "customize_count": row.get("customizeCount"),
                    "overwrite_type": row.get("overwriteProduceCardGrowEffectType"),
                    "grow_effects": effects})
            entry["count_status"] = "unique_master_candidate" if len(rows) == 1 else "ambiguous_master_candidates"
            entry["basis"] = "executed_id_and_exact_version_master_candidates"
        except (KeyError, OSError, AttributeError, TypeError, ValueError, sqlite3.Error, CatalogUnavailable):
            entry["candidate_transformations"] = []
            entry["basis"] = "executed_id_only/master_unavailable_or_incomplete"
        result["executed_customizations"].append(entry)
    return result


def semantic_context(value):
    """Remove transaction/frame provenance before deciding whether to replan."""
    if isinstance(value, list):
        return [semantic_context(v) for v in value]
    if isinstance(value, dict):
        return {k: semantic_context(v) for k, v in value.items()
                if k not in ("transaction_id", "event_seq", "source")}
    return value
