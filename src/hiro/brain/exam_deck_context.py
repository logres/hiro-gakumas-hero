"""Expose owned-card ledger definitions without asserting current exam piles."""
import os
from dataclasses import replace

from hiro.brain.mechanism_card_selection import build_context
from hiro.contracts import GameState
from hiro.state.catalog import CatalogUnavailable,catalog

FLAG = "HIRO_EXAM_DECK_CONTEXT"
PREFIX = "考试持有牌组记账候选："


def enabled():
    return os.environ.get(FLAG) == "1"


def recorded_exam_deck_context(state=None):
    """Reuse the existing exact-version context, including duplicates/unknowns.

    Card effects/costs remain catalog definitions. In particular, no text parser
    converts uncertain resource thresholds into verified payable transitions.
    """
    state=state if state is not None else GameState()
    unavailable=False
    try:
        master=catalog()
    except (CatalogUnavailable,OSError):
        master=None
        unavailable=True
    # Empty identity/candidates prevent unrelated selection or idol lookups.
    context=build_context(replace(state,page_fields={"candidates":[]}),{}, {},master)["deck"]
    context["recorded_inventory_complete"]=context["complete"]
    # Produce inventory includes exam-used cards; even a complete inventory is
    # not proof of the current draw/grave/excluded sets or their future draws.
    context["complete"]=False
    context["absence_claim_allowed"]=False
    context["current_exam_piles_status"]="not_established_by_owned_inventory"
    result={"scope":"produce_owned_ledger/not_current_exam_piles","deck":context,
            "note":"所列是培育持有记账候选，不是当前山札/弃牌/除外，也不提供顺序或重抽保证；"
                    "未知版本不按0级补齐，重复条目保留为不同持有记录但不定位当前副本。"
                    "主数据效果与费用用于提示可能的资源供给/消费，不证明定制、临时强化或当前可支付性。"
                    "pending/不完整记账不能用于断言没有某牌或其他资源来源；即使持有完整也不能据此断言当前牌堆缺牌。"}
    if unavailable:
        result["master_data"]="unavailable"
    return result
