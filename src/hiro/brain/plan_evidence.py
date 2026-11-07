"""Compare actual effect information behind a plan, excluding frame provenance."""
import copy
import json
import os

KEY = "_effect_basis"
PREFIXES = ("已验证主数据与本帧装备识别：", "本帧卡牌详情原始证据：", "本帧考试分组快照：", "本帧持续卡效果候选：", "本帧持续饮料效果候选：", "考试持有牌组记账候选：", "本帧状态读数证据：")


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
    cards, equipment, groups, active = {}, [], {}, None
    active_drinks=None
    owned_deck=None
    typed_statuses=None
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
        if prefix == PREFIXES[6]:
            if data.get("observation_status")=="available":
                typed_statuses=[{k:row.get(k) for k in ("kind","key","name","card_id","observed_asset",
                    "value","unit","value_status","duration_status","duration_basis","duration_conflict","catalog_duration_status")}
                    for row in data.get("statuses") or [] if isinstance(row,dict)]
                for row in typed_statuses:
                    if row.get("kind")=="status" and row.get("key") in ("examcardplayaggressive","examreview"):
                        row.pop("value",None)  # Ordinary resource changes are already in BattleState.
                typed_statuses.sort(key=lambda row:json.dumps(row,sort_keys=True))
        elif prefix == PREFIXES[5]:
            deck=data.get("deck")
            if data.get("scope")=="produce_owned_ledger/not_current_exam_piles" and isinstance(deck,dict):
                owned_deck={k:deck.get(k) for k in ("recorded_size","observed_count","source","field_status","pending_review",
                    "versions_known","recorded_inventory_complete","absence_claim_allowed","customization_effects_known")}
                cards_read=deck.get("observed_cards")
                owned_deck["observed_cards"]=sorted(cards_read,key=lambda card:json.dumps(card,sort_keys=True)) if isinstance(cards_read,list) else None
        elif prefix == PREFIXES[4]:
            if data.get("observation_status")=="available":
                active_drinks=[{k:drink.get(k) for k in ("observed_asset","identity_status","actual_source_version",
                    "actual_modifications_status","observed_value","observed_unit","master_lookup_status","candidate_variants")}
                    for drink in data.get("drinks") or [] if isinstance(drink,dict)]
                active_drinks.sort(key=lambda drink:json.dumps(drink,sort_keys=True))
        elif prefix == PREFIXES[3]:
            if data.get("observation_status")=="available":
                active=[{k:card.get(k) for k in ("observed_card_id","identity_status","actual_upgrade_status",
                    "customization_effects_known","observed_value","observed_unit","candidate_variants")}
                    for card in data.get("cards") or [] if isinstance(card,dict)]
                active.sort(key=lambda card:json.dumps(card,sort_keys=True))
        elif prefix == PREFIXES[1]:
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
        elif prefix == PREFIXES[2]:
            if data.get("scope") != "current_exam_groups" or data.get("restoration_verified") is not True:
                continue
            for group in data.get("groups") or []:
                if not isinstance(group, dict) or group.get("pile") not in ("draw", "grave", "excluded"):
                    continue
                count = group.get("count")
                if type(count) is not int or count < 0:
                    continue
                value = {"count": count, "complete": group.get("complete") is True}
                if value["complete"]:
                    value["cards"] = sorted([{k: c.get(k) for k in ("card_id", "observed_thumbnail_upgrade", "customized")}
                                             for c in group.get("cards") or [] if isinstance(c, dict)],
                                            key=lambda c: json.dumps(c, sort_keys=True))
                groups[group["pile"]] = value
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
    return {"version": 1, "cards": cards, "exam_groups": groups,"active_card_effects":active,"active_drink_effects":active_drinks,
            "owned_deck":owned_deck, "typed_statuses":typed_statuses,
            "equipment": sorted(equipment, key=lambda v: json.dumps(v, sort_keys=True))}


def changed(plan, state):
    current = effect_basis(state)
    old = plan[0].get(KEY) if plan and isinstance(plan[0], dict) else None
    if not isinstance(old, dict) or old.get("version") != 1:
        return bool(current["cards"] or current["equipment"] or current["exam_groups"] or current["active_card_effects"] or current["active_drink_effects"] or current["owned_deck"] or current["typed_statuses"])
    previous_cards = old.get("cards") or {}
    return (any(previous_cards.get(key) != value for key, value in current["cards"].items())
            or bool(current["equipment"] and current["equipment"] != old.get("equipment"))
            or any((old.get("exam_groups") or {}).get(key) != value for key,value in current["exam_groups"].items())
            or bool(current["active_card_effects"] is not None
                    and (current["active_card_effects"] or old.get("active_card_effects"))
                    and current["active_card_effects"]!=old.get("active_card_effects"))
            or bool(current["active_drink_effects"] is not None
                    and (current["active_drink_effects"] or old.get("active_drink_effects"))
                    and current["active_drink_effects"]!=old.get("active_drink_effects"))
            or bool(current["owned_deck"] is not None and current["owned_deck"]!=old.get("owned_deck"))
            or bool(current["typed_statuses"] is not None and current["typed_statuses"]!=old.get("typed_statuses")))


def stamp(plan, state):
    basis = effect_basis(state)
    return [{**step, KEY: copy.deepcopy(basis)} for step in public_plan(plan)]
