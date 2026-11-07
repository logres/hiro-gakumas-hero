"""Generate auditable abstract resource-horizon fixtures. No game/model access.

These are standalone synthetic reasoning inputs, not game BattleState snapshots,
game-rule simulations, master-data claims, or evidence of real model quality.
Only the explicitly closed two-turn arithmetic below supplies the oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

VERSION = "1.0"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def validate_input(data):
    """Reject unspecified mechanics instead of silently simulating them."""
    if not isinstance(data, dict) or data.get("scope") != "synthetic_resource_horizon/not_game_simulation":
        raise ValueError("explicit standalone synthetic scope required")
    closed = data.get("closed_assumptions")
    required = {"current_actions": 1, "resource_decay": 0, "other_resource_sources": False,
                "other_score_sources": False, "other_triggers": False,
                "target_uses_next_turn": 1, "target_resource_payment": 0,
                "current_cards_use_one_action_each": True}
    if closed != required or any(type(closed[k]) is not type(v) for k,v in required.items()):
        raise ValueError("closed assumptions changed or incomplete")
    resource = data.get("resource")
    if (not isinstance(resource, dict) or not isinstance(resource.get("key"), str)
            or not resource["key"].strip() or len(resource["key"]) > 80
            or type(resource.get("current")) is not int or resource["current"] < 0):
        raise ValueError("known resource identity/current amount required")
    if type(data.get("turns_remaining")) is not int or data["turns_remaining"] not in (1,2):
        raise ValueError("only this closed one/two-turn horizon is supported")
    cards = data.get("current_cards")
    if not isinstance(cards, list) or len(cards) != 2:
        raise ValueError("exactly two current actions required")
    if {c.get("id") for c in cards if isinstance(c, dict)} != {"supplier", "filler"}:
        raise ValueError("supplier/filler identity missing or duplicated")
    if any(type(c.get("slot")) is not int for c in cards) or {c["slot"] for c in cards} != {0,1}:
        raise ValueError("distinct exact physical slots required")
    for card in cards:
        if (card.get("resource_key") != resource["key"] or card.get("available") is not True
                or type(card.get("immediate_score")) is not int or card["immediate_score"] < 0
                or (card.get("resource_gain") is not None and
                    (type(card["resource_gain"]) is not int or card["resource_gain"] < 0))):
            raise ValueError("current action identity/effects unknown or malformed")
    supplier = next(c for c in cards if c["id"] == "supplier")
    filler = next(c for c in cards if c["id"] == "filler")
    if supplier["immediate_score"] != 0 or filler["immediate_score"] != 2 or filler["resource_gain"] != 0:
        raise ValueError("fixture current-score/gain premises changed")
    target = data.get("next_turn_target")
    if (not isinstance(target, dict) or target.get("resource_key") != resource["key"]
            or target.get("id") != "gated_target" or type(target.get("score")) is not int or target["score"] != 9
            or (target.get("threshold") is not None and
                (type(target["threshold"]) is not int or target["threshold"] < 0))):
        raise ValueError("target threshold or score malformed")
    availability = target.get("availability")
    if not isinstance(availability, dict) or availability.get("status") not in ("guaranteed", "unknown", "probability"):
        raise ValueError("explicit target availability required")
    status, probability = availability["status"], availability.get("probability")
    if status == "probability":
        if (type(probability) not in (int,float) or not math.isfinite(probability) or not 0 <= probability <= 1):
            raise ValueError("explicit probability must be finite in [0,1]")
    elif probability is not None:
        raise ValueError("unknown/guaranteed availability must not fabricate a numeric probability")
    return data


def oracle(data):
    """Exact arithmetic only under validate_input's explicit toy assumptions."""
    validate_input(data)
    cards = {c["id"]:c for c in data["current_cards"]}
    target = data["next_turn_target"]
    unknown = []
    if cards["supplier"]["resource_gain"] is None:unknown.append("supplier_gain")
    if target["threshold"] is None:unknown.append("target_threshold")
    if unknown:
        return {"status":"no_strict_oracle_unknown_effect", "strict_action":None,
                "unknown_fields":unknown, "expected_values":None,
                "note":"Unknown customized gain/threshold is not assigned a guessed value."}
    future = data["turns_remaining"] == 2
    status = target["availability"]["status"]
    probability = (1 if status == "guaranteed" else target["availability"]["probability"])
    current = data["resource"]["current"]
    can_use = {key:current+card["resource_gain"] >= target["threshold"] for key,card in cards.items()}
    expressions = {key:{"constant":card["immediate_score"], "p_coefficient":target["score"] if future and can_use[key] else 0}
                   for key,card in cards.items()}
    if status == "unknown" and future:
        delta_constant = expressions["supplier"]["constant"]-expressions["filler"]["constant"]
        delta_coefficient = expressions["supplier"]["p_coefficient"]-expressions["filler"]["p_coefficient"]
        if delta_coefficient == 0:
            best = max(expressions,key=lambda key:expressions[key]["constant"])
            unique = delta_constant != 0
            action = {"card_id":best,"slot":cards[best]["slot"]} if unique else None
            return {"status":"unique_action" if unique else "tied_no_unique_action",
                    "strict_action":action,"unknown_fields":["target_availability_probability"],
                    "probability_used":None,"expected_values":None,"comparison":expressions,
                    "note":"Equal future p coefficients cancel; only the known immediate constants differ. No probability was imputed."}
        return {"status":"no_unique_action_oracle_unknown_probability", "strict_action":None,
                "unknown_fields":["target_availability_probability"], "probability_used":None,
                "comparison":expressions,
                "supplier_better_if_p_greater_than":-delta_constant/delta_coefficient if delta_coefficient > 0 else None,
                "note":"For the R=1 fixture: supplier=9p versus filler=2; unknown p is neither 0 nor 1."}
    # In the last turn target availability has no payoff and needs no p estimate.
    probability_used = probability if future else None
    values = {key:term["constant"]+(probability*term["p_coefficient"] if future else 0)
              for key,term in expressions.items()}
    best_value = max(values.values())
    best = [key for key,value in values.items() if math.isclose(value,best_value,rel_tol=0,abs_tol=1e-12)]
    action = {"card_id":best[0], "slot":cards[best[0]]["slot"]} if len(best) == 1 else None
    return {"status":"unique_action" if action else "tied_no_unique_action", "strict_action":action,
            "expected_values":values, "probability_used":probability_used, "comparison":expressions,
            "note":"Arithmetic for this closed synthetic horizon only; not a game simulator."}


def build_fixtures(resource_names=("R", "resource_beta")):
    if not resource_names or len(set(resource_names)) != len(resource_names):
        raise ValueError("distinct resource aliases required")
    variants = [
        ("guaranteed_next_turn",1,2,3,4,"guaranteed",None),
        ("already_at_threshold",4,2,3,4,"guaranteed",None),
        ("final_turn",1,1,3,4,"guaranteed",None),
        ("unknown_future_probability",1,2,3,4,"unknown",None),
        ("explicit_probability_half",1,2,3,4,"probability",.5),
        ("explicit_probability_tenth",1,2,3,4,"probability",.1),
        ("unknown_customized_supplier_gain",1,2,None,4,"guaranteed",None),
        ("unknown_customized_target_threshold",1,2,3,None,"guaranteed",None),
    ]
    fixtures=[]
    for resource in resource_names:
        for name,current,remaining,gain,threshold,status,p in variants:
            for swapped in (False,True):
                cards=[{"id":"supplier","slot":0,"available":True,"resource_key":resource,"immediate_score":0,"resource_gain":gain},
                       {"id":"filler","slot":1,"available":True,"resource_key":resource,"immediate_score":2,"resource_gain":0}]
                if swapped:
                    for card in cards:card["slot"]=1-card["slot"]
                    cards.reverse()
                model_input={"scope":"synthetic_resource_horizon/not_game_simulation", "turns_remaining":remaining,
                    "resource":{"key":resource,"current":current}, "current_cards":cards,
                    "next_turn_target":{"id":"gated_target","resource_key":resource,"threshold":threshold,"score":9,
                                        "availability":{"status":status,"probability":p}},
                    "closed_assumptions":{"current_actions":1,"resource_decay":0,"other_resource_sources":False,
                        "other_score_sources":False,"other_triggers":False,"target_uses_next_turn":1,
                        "target_resource_payment":0,"current_cards_use_one_action_each":True},
                    "task":"Choose one current card by slot. Explain expected total payoff under only these premises; unknown numbers stay unknown. Future target is not a current legal action."}
                expected=oracle(model_input)
                fixtures.append({"id":f"{name}/{resource}/swap-{int(swapped)}", "scenario":name,
                                 "model_input":model_input,"model_input_sha256":_hash(model_input),
                                 "oracle":expected,"oracle_sha256":_hash(expected)})
    return fixtures


def judge_action(fixture, response):
    """Strict action checks only; no automated scoring of reasoning prose."""
    validate_input(fixture["model_input"])
    if _hash(fixture["model_input"]) != fixture["model_input_sha256"] or _hash(fixture["oracle"]) != fixture["oracle_sha256"]:
        raise ValueError("fixture hash mismatch")
    if fixture["oracle"] != oracle(fixture["model_input"]):
        raise ValueError("oracle does not follow the current closed assumptions")
    slot=response.get("slot") if isinstance(response,dict) else None
    legal=type(slot) is int and slot in {card["slot"] for card in fixture["model_input"]["current_cards"]}
    expected=fixture["oracle"]["strict_action"]
    return {"legal":legal,"strict_action_applicable":expected is not None,
            "strict_action_pass":legal and slot==expected["slot"] if expected is not None else None,
            "reasoning_quality":"not_evaluated", "model_quality":"not_established_by_fixture_or_mock"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--resource",action="append",dest="resources",help="resource alias; repeat to test renaming")
    args=parser.parse_args(argv)
    try:
        fixtures=build_fixtures(args.resources or ("R","resource_beta"))
    except (ValueError,TypeError) as exc:
        parser.error(str(exc))
    report={"schema":"synthetic_resource_horizon@"+VERSION,"scope":"standalone synthetic reasoning; not BattleState/replay/game simulation",
            "generator_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "model_calls":0,"private_inputs_read":False,"fixture_count":len(fixtures),"fixtures":fixtures}
    text=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding="utf-8")
        print(json.dumps({"output":str(args.output),"fixture_count":len(fixtures),"model_calls":0}))
    else:print(text)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
