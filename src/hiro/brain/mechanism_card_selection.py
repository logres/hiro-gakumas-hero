"""Optional mechanism comparison over already eligible ordinary card picks."""

import os
from dataclasses import replace

from hiro.brain.cards import description_text
from hiro.brain.route_policy import explicit_route_enabled
from hiro.contracts import Action, Candidate, Decision, llm_trace_from_call
from hiro.state.catalog import CatalogUnavailable


def enabled():
    return explicit_route_enabled() and os.environ.get("HIRO_MECHANISM_CARD_SELECTION") == "1"


def _view(card_id, upgrade, row, observed):
    return {"card_id": card_id, "upgrade": upgrade, "name": row.get("name"),
            "master_effect_text": description_text(row.get("produceDescriptions")) or None,
            "effect_groups": row.get("effectGroupIds"), "category": row.get("category"),
            "rarity": row.get("rarity"), "plan": row.get("planType"),
            "costs": {key: row.get(key) for key in ("stamina", "forceStamina", "costType", "costValue")},
            "observed_customized": observed.get("customized"),
            "effects_basis": "Master card_id+upgrade only; actual customization effects are unknown."}


def build_context(state, idol, eligible_rows, catalog):
    """Prepare a read-only, route-neutral context, without making a model call."""
    raw = state.page_fields.get("candidates") or []
    candidates = [{"index": index, **_view(raw[index]["card_id"], raw[index]["upgrade"], row, raw[index])}
                  for index, row in eligible_rows.items()]
    produce = state.produce or {}
    raw_deck = produce.get("deck")
    deck = None if raw_deck is None else []
    versions_known = isinstance(raw_deck, list)
    for entry in raw_deck or []:
        card = entry if isinstance(entry, dict) else vars(entry)
        cid, upgrade = card.get("card_id"), card.get("upgrade")
        row = None
        if cid and type(upgrade) is int and upgrade >= 0:
            try:
                row = catalog.card(cid, upgrade)
            except (CatalogUnavailable, KeyError, OSError):
                pass
        if row is None:
            versions_known = False
            deck.append({"card_id": cid, "upgrade": upgrade, "master_effect_text": None,
                         "observed_customized": card.get("customized"), "unknown": True})
        else:
            deck.append(_view(cid, upgrade, row, card))
    source = state.sources.get("produce.deck")
    origin = getattr(source, "origin", None)
    verified = (state.field_status.get("produce.deck") == "verified"
                and not {"produce.deck", "produce.deck_size"}.intersection(state.pending_review)
                and state.field_status.get("produce.deck_size") not in ("pending", "unknown"))
    complete = bool(versions_known and verified and type(produce.get("deck_size")) is int
                    and len(raw_deck) == produce["deck_size"])
    return {"idol": {key: idol.get(key) for key in ("id", "name", "characterId", "planType", "examEffectType",
                                                   "produceCardId", "beforeProduceItemId", "afterProduceItemId")},
            "stage": {"mode": produce.get("mode"), "step": produce.get("step")},
            "resources": {key: produce.get(key) for key in ("stamina", "max_stamina", "produce_point", "params", "growth_permil")},
            "deck": {"observed_cards": deck, "recorded_size": produce.get("deck_size"),
                     "observed_count": len(raw_deck) if isinstance(raw_deck, list) else None,
                     "complete": complete, "source": origin, "field_status": state.field_status.get("produce.deck"),
                     "versions_known": versions_known,
                     "absence_claim_allowed": complete,
                     "customization_effects_known": False},
            "game_recommended_index": state.page_fields.get("recommended"), "candidates": candidates,
            "allowed_action": "pick one listed original index only; no reroll, exclude, change, remove or skip"}


def compare(decider, state, idol, eligible_rows, catalog, fallback):
    if not enabled():
        return fallback
    if decider.llm is None:
        return replace(fallback, warnings=[*fallback.warnings, "机制选卡未配置模型，保留既有规则结果"])
    try:
        payload = build_context(state, idol, eligible_rows, catalog)
    except (ValueError, TypeError, AttributeError) as exc:
        return replace(fallback, warnings=[*fallback.warnings, f"机制上下文字段不完整，保留既有规则：{type(exc).__name__}"])
    # Unknown candidate text is not a basis for a mechanism comparison.
    payload["candidates"] = [card for card in payload["candidates"] if card["master_effect_text"]]
    if not payload["candidates"]:
        return replace(fallback, warnings=[*fallback.warnings, "机制选卡候选完整文本未知，保留既有规则结果"])
    calls = []
    error = None
    try:
        data, calls = decider._ask(["mechanism_card_pick.md"], payload)
    except Exception as exc:
        data = None
        error = f"{type(exc).__name__}: {exc}"
        calls = [{"adapter": getattr(decider.llm, "name", "unknown"), "model": getattr(decider.llm, "model", None), "error": error}]
    traces = [llm_trace_from_call(call) for call in calls]
    valid_indices = {card["index"] for card in payload["candidates"]}
    if (not isinstance(data, dict) or data.get("action") != "pick" or type(data.get("index")) is not int
            or data["index"] not in valid_indices or not isinstance(data.get("reason"), str) or not data["reason"].strip()):
        return replace(fallback, reason="机制模型无有效选择，保留既有规则：" + fallback.reason,
                       warnings=[*fallback.warnings, error or "机制选卡输出非法或调用失败；未刷新/删换卡"], llm=traces)
    candidates = [Candidate(Action.activate_effect(card["index"]), preview=card) for card in payload["candidates"]]
    return Decision(Action.activate_effect(data["index"]), data["reason"].strip(), "llm", None, candidates,
                    llm=traces, decider="mechanism_card_selection")
