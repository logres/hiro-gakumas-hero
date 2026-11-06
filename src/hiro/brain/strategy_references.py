"""Versioned advisory references, selected by verified mechanism and exam stage."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from hiro.brain.route_policy import explicit_route_enabled
from hiro.state.catalog import CatalogUnavailable, catalog as default_catalog

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "defaults/strategy_refs"


def enabled():
    return explicit_route_enabled() and os.environ.get("HIRO_EXAM_STRATEGY_REFERENCES") == "1"


def select_references(identity, exam_label, catalog=None):
    """Unknown identity or stage selects nothing; no character-ID special cases."""
    if not enabled() or not identity or not isinstance(exam_label, str):
        return []
    identity = identity.replace("i_card-skin-", "i_card-")
    try:
        idol = (catalog or default_catalog()).one("IdolCard", identity)
    except (CatalogUnavailable, KeyError, OSError, sqlite3.Error):
        return []
    selected = []
    for path in sorted(REFERENCE_DIR.glob("*.json")):
        raw = path.read_bytes()
        reference = json.loads(raw)
        applicability = reference["applicability"]
        if (idol.get("examEffectType") not in applicability["recommended_effects"]
                or exam_label not in applicability["exam_labels"]):
            continue
        selected.append({**reference, "sha256": hashlib.sha256(raw).hexdigest(),
                         "selection_evidence": {"idol_card_id": identity, "recommended_effect": idol["examEffectType"],
                                                "exam_label": exam_label}})
    return selected


def audit_suffix(references):
    """The payload retains full hashes; compact tags fit existing LLMTrace."""
    return "".join(f"+strategy:{ref['id']}@{ref['version']}#{ref['sha256'][:12]}"
                   for ref in sorted(references, key=lambda item: item["id"]))
