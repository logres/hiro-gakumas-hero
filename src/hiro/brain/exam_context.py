"""Verified identity and observed equipment facts; no inferred awakening/equipment."""

import sqlite3

from hiro.brain.cards import description_text
from hiro.state.catalog import CatalogUnavailable, catalog

_UNAVAILABLE = (CatalogUnavailable, KeyError, OSError, sqlite3.Error)


def _item(row: dict) -> dict:
    try:
        text = description_text(row.get("produceDescriptions")) or None
    except (ValueError, TypeError, AttributeError):
        text = None
    return {"item_id": row["id"], "name": row.get("name"), "effect_text": text}


def verified_exam_context(idol_card_id: str | None, observed_pitems: list | None) -> dict:
    """Only exact item IDs confirm a variant; an icon may identify several variants.

    Candidate descriptions are alternatives, never combined active effects. The
    idol's before/after references are separately labelled identity expectations.
    """
    out = {"identity": {"status": "unknown"}, "observed_pitems": [],
           "equipment_note": "仅列本帧识别到的道具；候选版本不是已确认生效的效果。未列出不等于未装备。"}
    try:
        master = catalog()
    except _UNAVAILABLE:
        out["master_data"] = "unavailable"
        return out
    if idol_card_id:
        identity = idol_card_id.replace("i_card-skin-", "i_card-")
        try:
            idol = master.one("IdolCard", identity)
            out["identity"] = {"status": "verified_master", "idol_card_id": idol["id"],
                               "card_name": idol.get("name"), "character_id": idol.get("characterId"),
                               "plan_type": idol.get("planType"), "recommended_effect": idol.get("examEffectType")}
            identity_variants = []
            for key in ("beforeProduceItemId", "afterProduceItemId"):
                item_id = idol.get(key)
                if not item_id or any(it["item_id"] == item_id for it in identity_variants):
                    continue
                try:
                    identity_variants.append(_item(master.one("ProduceItem", item_id)))
                except _UNAVAILABLE:
                    pass
            if identity_variants:
                out["catalog_identity_item_variants"] = {
                    "status": "expected_from_identity/not_observed",
                    "actual_upgrade_status": "unknown",
                    "variants": identity_variants,
                    "note": "仅为该偶像卡主数据关联的可能道具机制；未由装备识别确认，不代表已装备、实际强化版本、剩余次数或已经触发。候选效果不能叠加。",
                }
            try:
                char = master.one("Character", idol.get("characterId") or "")
                out["identity"]["character_name"] = "".join(char.get(k) or "" for k in ("lastName", "firstName")) or None
            except _UNAVAILABLE:
                pass
        except _UNAVAILABLE:
            pass
    for observed in observed_pitems or []:
        if not isinstance(observed, dict):
            continue
        fact = {"slot": observed.get("slot"), "variant_status": "unknown"}
        for key in ("rect", "charges_box", "remaining_charges", "charges_source"):
            if key in observed:
                fact[key] = observed[key]
        item_id = observed.get("item_id") or observed.get("id")
        if item_id:
            fact["observed_item_id"] = item_id
            try:
                fact.update(_item(master.one("ProduceItem", item_id)), variant_status="confirmed_id")
            except _UNAVAILABLE:
                pass
        elif observed.get("asset"):
            # Same icon is often shared by normal/+ variants. Never choose one.
            asset = observed["asset"]
            fact["observed_asset"] = asset
            try:
                rows = master.db.execute('SELECT * FROM "ProduceItem" WHERE assetId = ? ORDER BY id', (asset,)).fetchall()
                candidates = [_item(dict(row)) for row in rows]
                if candidates:
                    fact["candidate_variants"] = candidates
                    fact["variant_note"] = "图标匹配到这些主数据候选，实际版本及强化状态未确认；不得将候选叠加或默认强化版。"
            except _UNAVAILABLE:
                pass
        out["observed_pitems"].append(fact)
    return out
