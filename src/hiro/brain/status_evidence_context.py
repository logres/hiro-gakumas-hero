"""Current-frame status presence, numeric readings and duration evidence."""
import os

FLAG = "HIRO_TYPED_STATUS_CONTEXT"
PREFIX = "本帧状态读数证据："


def enabled():
    return os.environ.get(FLAG) == "1"


def observed_status_context(raw_statuses):
    """Never infer permanence from a missing counter, catalog or history."""
    result = {"observation_status": "available" if isinstance(raw_statuses, list) else "not_available",
              "statuses": [],
              "note": "图标存在不证明数值已知；null本身不证明永久。主数据永久候选不代表实际持续时间。"
                      "重复观察不是叠层数；未知不补0。"}
    if not isinstance(raw_statuses, list):
        return result
    for raw in raw_statuses:
        if not isinstance(raw, dict):
            continue
        value = raw.get("value")
        numeric = type(value) is int and value >= 0
        unit = raw.get("unit")
        entry = {"observed_slot": raw.get("slot"), "kind": raw.get("kind"),
                 "key": raw.get("key"), "name": raw.get("name"),
                 "card_id": raw.get("card_id"), "observed_asset": raw.get("observed_asset"),
                 "value": value if numeric else None, "unit": unit,
                 "value_status": "observed_number" if numeric else "unknown",
                 "duration_status": "unknown"}
        proof = raw.get("permanent_proof")
        if isinstance(proof, dict) and proof.get("master_duration_basis") == "candidate_only":
            entry["catalog_duration_status"] = "permanent_candidate_only"
        explicit = raw.get("actual_duration_evidence")
        if (isinstance(explicit, dict) and explicit.get("verified") is True
                and explicit.get("source") == "current_screen" and explicit.get("status") == "permanent"):
            if numeric and value > 0 and unit in ("ターン", "回", "turn", "count"):
                entry["duration_conflict"] = "explicit_permanent_vs_observed_positive_counter"
            else:
                entry["duration_status"] = "permanent"
                entry["duration_basis"] = "explicit_verified_current_screen"
        elif numeric and unit in ("ターン", "回", "turn", "count"):
            entry["duration_status"] = "finite"
            entry["duration_basis"] = "observed_number_and_unit"
        result["statuses"].append(entry)
    return result
