"""Scope legacy やる気 policies to a confirmed master-data recommendation.

This does not infer a new build or rank cards for other routes. The explicit
identity rollout switch preserves existing behavior when disabled.
"""

import os
import sqlite3

from hiro.state.catalog import CatalogUnavailable, catalog

YARUKI_EFFECT = "ExamCardPlayAggressive"
ROUTE_POLICY_SKIP = "route_policy_skip"


def explicit_route_enabled() -> bool:
    return os.environ.get("HIRO_EXPLICIT_IDOL_STATE") == "1"


def legacy_exam_policy(state) -> bool:
    """Empirical やる気 constraints require a verified route in explicit mode."""
    return (not explicit_route_enabled() or getattr(state, "recommended_effect", None)
            == "ProduceExamEffectType_ExamCardPlayAggressive")


def recommended_effect(idol_card_id: str | None) -> str | None:
    """Read IdolCard.examEffectType; absent/unknown data stays unknown."""
    if not idol_card_id:
        return None
    identity = idol_card_id.replace("i_card-skin-", "i_card-")
    try:
        row = catalog().one("IdolCard", identity)
    except (CatalogUnavailable, KeyError, OSError, sqlite3.Error):
        return None
    effect = row.get("examEffectType")
    prefix = "ProduceExamEffectType_"
    if not isinstance(effect, str) or not effect.startswith(prefix):
        return None
    effect = effect[len(prefix):]
    return None if effect in ("", "Unknown") else effect


def yaruki_route(idol_card_id: str | None) -> bool:
    """Only the master-data やる気 recommendation enables its specialist policy."""
    return recommended_effect(idol_card_id) == YARUKI_EFFECT


def legacy_or_yaruki(idol_card_id: str | None) -> bool:
    """Legacy mode is unchanged; explicit unknown/non-やる気 routes are excluded."""
    return not explicit_route_enabled() or yaruki_route(idol_card_id)
