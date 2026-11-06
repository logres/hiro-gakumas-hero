"""Explainable fallback scores and optional final-action numeric tie-breaking.

Catalog text is a heuristic input, never verification of customized effects,
equipment triggers, card movement, or actual effect dominance.
"""
import json
import os
import re
from dataclasses import asdict

FLAG = "HIRO_FALLBACK_EFFECT_SCORING"
_DIRECT = re.compile(r"パラメータ\+([0-9]+)(?:元気\+([0-9]+))?")


def enabled():
    return os.environ.get(FLAG) == "1"


def primary_terms(state, card, cash):
    """The existing policy weights, decomposed without changing their values."""
    t = card.tags
    last = state.remaining_turns is not None and state.remaining_turns <= 1
    many = state.actions_left is not None and state.actions_left > 1
    terms = {"extra_actions": 3.0*t.extra_actions, "draws": 1.5*t.draws,
             "installation": 2.5 if t.sustained_turns or (t.permanent_trigger and "以降、ターン開始時" not in card.text) else 0,
             "final_action_refund": 12 if last and state.gives_action(card) else 0,
             "nonclearing_cashout": ((6+(t.genki_score_pct or t.impression_score_pct)/100) if last else 0)
                                    if card in cash and not t.clears_genki else 0,
             "clearing_cashout": ((10-(3 if many and len(cash)>1 else 0)) if last else -20) if t.clears_genki else 0,
             "empty_genki_cashout": -30 if t.genki_score_pct and state.genki == 0 and "元気+" not in card.text else 0,
             "cost": -0.2*(card.cost+2*card.hp_cost)}
    return terms


def _payable(state, card):
    values = (state.hp,state.genki,card.cost,card.hp_cost)
    return (all(type(v) is int and v >= 0 for v in values) and card.extra_cost is None
            and state.hp >= card.hp_cost+max(0,card.cost-state.genki))


def choose(state, candidates, scores):
    """Return (card, audit), preserving primary priorities and unknown values.

    Only ties between the same typed cost/category/tag signature are considered.
    Mixed known/missing badges never fall through to catalog comparison. Catalog
    comparison is full-text, same-shape and rejects numerical trade-offs. This
    is a tie heuristic, not candidate pruning or an execution constraint.
    """
    original = max(candidates,key=lambda card:scores[card.slot])
    tied = [card for card in candidates if scores[card.slot] == scores[original.slot]]
    audit = {"basis":"legacy_primary", "status":"unchanged", "reason":"not_applicable"}
    if (state.remaining_turns != 1 or type(state.actions_left) is not int or state.actions_left != 1 or len(tied)<2):
        return original,audit
    reference = tied[0]
    signature = lambda c:(c.category,c.cost,c.hp_cost,c.extra_cost,asdict(c.tags))
    if (reference.category != "active" or any(signature(c)!=signature(reference) or not _payable(state,c) for c in tied)
            or reference.tags.extra_actions or reference.tags.draws or reference.tags.adds_turn
            or reference.tags.sustained_turns or reference.tags.permanent_trigger or reference.tags.delayed_turns):
        return original,{**audit,"reason":"mixed_mechanisms_costs_or_unproven_payment"}
    badges = [card.badge_score for card in tied]
    if all(type(value) is int and value >= 0 for value in badges):
        best=max(tied,key=lambda c:c.badge_score)
        return best,{"basis":"typed_badge_score", "status":"tie_compared", "values":{str(c.slot):c.badge_score for c in tied}}
    if any(value is not None for value in badges):
        return original,{**audit,"reason":"mixed_or_invalid_badge_evidence"}
    parsed=[]
    for card in tied:
        match=_DIRECT.fullmatch("".join(card.text.split()))
        if match is None:
            return original,{**audit,"reason":"catalog_text_not_complete_same_shape"}
        parsed.append((card,(int(match[1]),int(match[2]) if match[2] is not None else 0),match[2] is not None))
    if len({row[2] for row in parsed}) != 1:
        return original,{**audit,"reason":"catalog_text_not_complete_same_shape"}
    maxima=tuple(max(row[1][i] for row in parsed) for i in range(2))
    possible=[card for card,vector,_ in parsed if vector==maxima]
    if not possible:
        return original,{**audit,"reason":"numeric_tradeoff_not_ranked"}
    return possible[0],{"basis":"catalog_text_heuristic/not_actual_effect_verification", "status":"tie_compared",
        "values":{str(card.slot):{"direct_parameter":vector[0],"flat_genki":vector[1]} for card,vector,_ in parsed},
        "limits":"主数据启发式，不是实效或支配证明；未证明定制、道具触发、移动规则。"}


def reason(state,candidates,cash,selected,audit):
    rows=[{"slot":card.slot,"primary_terms":primary_terms(state,card,cash),
           "primary_total":sum(primary_terms(state,card,cash).values())} for card in candidates]
    return "兜底解释性评分："+json.dumps({"selected_slot":selected.slot,"candidates":rows,"tie_break":audit},ensure_ascii=False,separators=(",",":"))
