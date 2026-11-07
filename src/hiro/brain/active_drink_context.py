"""Current drink-enchant asset candidates -> alternative catalog mechanisms."""
import os

from hiro.brain.active_card_context import _MISSING, _persistent
from hiro.brain.cards import description_text
from hiro.state.catalog import catalog

FLAG = "HIRO_ACTIVE_DRINK_EFFECT_CONTEXT"
PREFIX = "本帧持续饮料效果候选："


def enabled():
    return os.environ.get(FLAG) == "1"


def observed_active_drink_context(raw_statuses):
    """No history or name binding. Visual asset candidates remain candidates."""
    result={"observation_status":"available" if isinstance(raw_statuses,list) else "not_available",
            "drinks":[],"ignored_other_kind_count":0,
            "note":"当前杯形图标仅是视觉asset候选；按公开关联列出饮料及持续机制互斥候选，不相加。"
                    "实际来源版本、修改及剩余次数未知，主数据期限/次数不代表当前余量。"
                    "persistent_effects仅为安装后的触发候选；drink_definition_text仅旁证，"
                    "不可把饮用时的即时效果重复计入每次触发。不由历史或相似名称确认来源。"}
    if not isinstance(raw_statuses,list):
        return result
    master=None
    drinks=[]
    try:
        master=catalog()
        drinks=master.rows("ProduceDrink")
    except _MISSING:
        result["master_data"]="unavailable"
    for observed in raw_statuses:
        if not isinstance(observed,dict) or observed.get("kind")!="drink_enchant":
            result["ignored_other_kind_count"]+=1
            continue
        asset=observed.get("observed_asset")
        entry={"observed_slot":observed.get("slot"),"observed_asset":asset,
               "visual_score":observed.get("score"),"visual_margin":observed.get("margin"),
               "observed_value":observed.get("value"),"observed_unit":observed.get("unit"),
               "identity_basis":"current_screen_masked_drink_asset_candidate",
               "identity_status":"visual_asset_candidate" if isinstance(asset,str) and asset else "unknown",
               "actual_source_version":"unknown","actual_modifications_status":"unknown",
               "remaining_trigger_count_status":"unknown","master_lookup_status":"unknown",
               "candidate_variants":[]}
        result["drinks"].append(entry)
        if not isinstance(asset,str) or not asset or master is None:
            continue
        matching=[row for row in drinks if row.get("assetId")==asset and isinstance(row.get("id"),str) and row["id"]]
        if not matching:
            continue
        entry["master_lookup_status"]="matching_asset_candidates"
        for row in sorted(matching,key=lambda row:row["id"]):
            candidate={"drink_id":row["id"],"name":row.get("name"),"asset_id":asset,
                       "drink_definition_text":description_text(row.get("produceDescriptions")) or None,
                       "definition_basis":"catalog_only/not_actual_modified_effect",
                       "drink_effect_associations":[],"persistent_effects_status":"unknown","persistent_effects":[]}
            entry["candidate_variants"].append(candidate)
            try:
                associations=[]
                for drink_effect_id in row.get("produceDrinkEffectIds") or []:
                    effect=master.one("ProduceDrinkEffect",drink_effect_id)
                    associations.append({"drink_effect_id":drink_effect_id,"exam_effect_id":effect.get("produceExamEffectId")})
                candidate["drink_effect_associations"]=associations
                links=[{"produceExamEffectId":link["exam_effect_id"]} for link in associations if link["exam_effect_id"]]
                persistent=_persistent(master,{"playEffects":links})
                if persistent:
                    candidate.update(persistent_effects_status="verified_catalog_associations",persistent_effects=persistent)
            except _MISSING:
                pass
    return result
