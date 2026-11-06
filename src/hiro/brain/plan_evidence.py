"""Compare actual effect information behind a plan, excluding frame provenance."""
import copy
import json
import os

KEY = "_effect_basis"
PREFIXES = ("已验证主数据与本帧装备识别：", "本帧卡牌详情原始证据：")


def enabled():
    return os.environ.get("HIRO_PLAN_EFFECT_REVALIDATION") == "1"


def public_plan(plan):
    """Only action hints, never private metadata or arbitrary model fields."""
    return [{k: step[k] for k in ("action", "card", "drink") if k in step}
            for step in plan if isinstance(step, dict)]


def _version(card_id, upgrade):
    if isinstance(card_id, str) and card_id and type(upgrade) is int and upgrade >= 0:
        return json.dumps([card_id, upgrade], ensure_ascii=False)
    return None


def effect_basis(state):
    """Known current details and observed equipment, not catalog identity guesses.

    Omit hashes, slots and OCR geometry/confidence. Known item charges affect
    trigger availability; None remains unknown. Missing detail
    observations do not assert an effect changed; newly supplied or changed
    observations for a remaining card do. Normal removal never invalidates.
    """
    remaining = {_version(c.card_id, c.upgrade) for c in state.hand}
    cards, equipment = {}, []
    for line in (state.public_info or "").splitlines():
        prefix = next((p for p in PREFIXES if line.startswith(p)), None)
        if prefix is None:
            continue
        try:
            data = json.loads(line[len(prefix):])
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if prefix == PREFIXES[1]:
            for card in data.get("cards") or []:
                if not isinstance(card, dict):
                    continue
                key = _version(card.get("card_id"), card.get("upgrade"))
                if key is None or key not in remaining:
                    continue
                vision = card.get("vision_transcription") or {}
                value = {"raw_ocr_lines": card.get("raw_ocr_lines"),
                         "ocr_completeness": card.get("ocr_completeness"),
                         "actual_effects_status": card.get("actual_effects_status")}
                if isinstance(vision, dict) and vision.get("status") == "model_transcription_unverified":
                    value["vision_transcription"] = {k: vision.get(k) for k in ("status", "lines", "uncertain_spans")}
                cards[key] = value
        else:
            for item in data.get("observed_pitems") or []:
                if not isinstance(item, dict):
                    continue
                value = {k: item[k] for k in ("variant_status", "observed_asset", "observed_item_id",
                                             "item_id", "effect_text", "remaining_charges") if k in item}
                candidates = item.get("candidate_variants")
                if isinstance(candidates, list):
                    value["candidate_variants"] = sorted(
                        [{k: c[k] for k in ("item_id", "effect_text") if k in c}
                         for c in candidates if isinstance(c, dict)], key=lambda c: json.dumps(c, sort_keys=True))
                if value:
                    equipment.append(value)
    return {"version": 1, "cards": cards,
            "equipment": sorted(equipment, key=lambda v: json.dumps(v, sort_keys=True))}


def changed(plan, state):
    current = effect_basis(state)
    old = plan[0].get(KEY) if plan and isinstance(plan[0], dict) else None
    if not isinstance(old, dict) or old.get("version") != 1:
        return bool(current["cards"] or current["equipment"])
    previous_cards = old.get("cards") or {}
    return (any(previous_cards.get(key) != value for key, value in current["cards"].items())
            or bool(current["equipment"] and current["equipment"] != old.get("equipment")))


def stamp(plan, state):
    basis = effect_basis(state)
    return [{**step, KEY: copy.deepcopy(basis)} for step in public_plan(plan)]
