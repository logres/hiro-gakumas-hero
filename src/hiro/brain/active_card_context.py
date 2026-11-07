"""Current enchant card IDs -> alternative catalog persistent mechanisms.

An icon does not establish upgrade, customization, activation count, or actual
installed effects. Original-card immediate gains are never recurring effects.
"""
import os
import sqlite3

from hiro.brain.cards import description_text
from hiro.state.catalog import CatalogUnavailable, catalog

PREFIX = "本帧持续卡效果候选："
FLAG = "HIRO_ACTIVE_CARD_EFFECT_CONTEXT"
_MISSING = (CatalogUnavailable,KeyError,OSError,sqlite3.Error,TypeError,ValueError,AttributeError)


def enabled():
    return os.environ.get(FLAG) == "1"


def _persistent(master,row):
    out=[]
    for play in row.get("playEffects") or []:
        if not isinstance(play,dict) or not play.get("produceExamEffectId"):
            continue
        installation=master.one("ProduceExamEffect",play["produceExamEffectId"])
        enchant_id=installation.get("produceExamStatusEnchantId")
        if not enchant_id or any(e["enchant_id"]==enchant_id for e in out):
            continue
        enchant=master.one("ProduceExamStatusEnchant",enchant_id)
        trigger_id=enchant.get("produceExamTriggerId")
        if not isinstance(trigger_id,str) or not trigger_id:
            raise ValueError("missing persistent trigger association")
        trigger=master.one("ProduceExamTrigger",trigger_id)
        effects=[]
        for effect_id in enchant.get("produceExamEffectIds") or []:
            effect=master.one("ProduceExamEffect",effect_id)
            effects.append({"effect_id":effect_id,"effect_type":effect.get("effectType"),
                            "effect_text":description_text(effect.get("produceDescriptions")) or None})
        text=description_text(enchant.get("produceDescriptions")) or None
        if not effects or not text:
            raise ValueError("missing persistent effect definition")
        out.append({"enchant_id":enchant_id,"installation_effect_id":play["produceExamEffectId"],
                    "active_effect_text":text,"trigger_id":trigger_id,
                    "trigger_definition_text":description_text(trigger.get("produceDescriptions")) or None,
                    "triggered_effects":effects,"catalog_installation_turns":installation.get("effectTurn"),
                    "catalog_installation_count":installation.get("effectCount"),
                    "current_remaining_turns_status":"not_inferred_from_catalog_duration",
                    "current_remaining_count_status":"unknown/not_inferred_from_catalog_limit"})
    return out


def observed_active_card_context(raw_statuses):
    """No history, name lookup, or deck inference. Input must be current raw statuses."""
    result={"observation_status":"available" if isinstance(raw_statuses,list) else "not_available",
            "cards":[],"ignored_non_enchant_count":0,
            "note":"只由本帧enchant图标的card_id确认来源卡；主数据版本是互斥候选，不可相加。"
                    "实际强化/定制及触发次数未知；同来源多个图标不证明叠层次数。"
                    "仅persistent_effects说明已安装后的触发候选，card_definition_text仅旁证，"
                    "不可再次计入原卡打出时的即时好印象/元气等收益。空/未知识别不证明没有持续效果。"}
    if not isinstance(raw_statuses,list):
        return result
    master=None
    try:
        master=catalog()
    except _MISSING:
        result["master_data"]="unavailable"
    for observed in raw_statuses:
        if not isinstance(observed,dict) or observed.get("kind")!="enchant":
            result["ignored_non_enchant_count"]+=1
            continue
        cid=observed.get("card_id")
        entry={"observed_slot":observed.get("slot"),"observed_card_id":cid,
               "observed_name":observed.get("name"),"observed_value":observed.get("value"),
               "observed_unit":observed.get("unit"),"identity_basis":"current_screen_enchant_card_id",
               "identity_status":"unknown","actual_upgrade_status":"unknown",
               "customization_effects_known":False,"remaining_trigger_count_status":"unknown",
               "candidate_variants":[]}
        result["cards"].append(entry)
        if not isinstance(cid,str) or not cid or master is None:
            continue
        try:
            rows=master.by_id("ProduceCard",cid)
        except _MISSING:
            continue
        valid=[row for row in rows if row.get("id")==cid and type(row.get("upgradeCount")) is int and row["upgradeCount"]>=0]
        if not valid:
            continue
        entry["identity_status"]="observed_base_card_id"
        for row in sorted(valid,key=lambda row:row["upgradeCount"]):
            candidate={"card_id":cid,"upgrade":row["upgradeCount"],"name":row.get("name"),
                       "card_definition_text":description_text(row.get("produceDescriptions")) or None,
                       "definition_basis":"catalog_only/not_actual_customized_effect",
                       "persistent_effects_status":"unknown","persistent_effects":[]}
            try:
                persistent=_persistent(master,row)
                if persistent:
                    candidate.update(persistent_effects=persistent,persistent_effects_status="verified_catalog_associations")
            except _MISSING:
                pass
            entry["candidate_variants"].append(candidate)
    return result
