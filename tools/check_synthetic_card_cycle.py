"""Public closed one-shot horizon cases via the actual generic pipeline.

Offline by default. Mock/guard success never establishes model decision quality.
Cycle membership checks enumerate possible orders without random probabilities.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
from hiro.brain.state import BattleState, ExamMemory
from hiro.contracts import Action
from hiro.contracts.trace import EXAM_REPLAY_FLAGS, freeze_exam_decision_input
from hiro.defaults.advisor import RuleLLMAdvisor
from hiro.brain.llm import from_spec
from tools import check_synthetic_generic_decisions as generic
from tools.check_synthetic_generic_decisions import SyntheticSource, _card
from tools import replay_exam_choice as replay
ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "examples/cases/card-cycle.json").read_text(encoding="utf-8"))

def cycle_oracle(case):
    # Membership over every possible ordering, without assigning probabilities.
    if not case["complete"]:
        return "uncertain"
    draws = [case["draw"] + list(order) for order in itertools.permutations(case["grave"])]
    outcomes = {"target" in draw[:case["draw_count"]] for draw in draws}
    return "guaranteed" if outcomes == {True} else "absent" if outcomes == {False} else "uncertain"


def freeze(case, *, swapped=False):
    # Explicit fixture premises are not an inferred idol rule or simulator output.
    assumptions = {"all_other_effects": [], "draw_modifiers": [], "retention": False,
                   "hand_limit": 5, "no_extra_draw_or_exclusion_recovery": True}
    if "target_next" in case:
        groups = [{"pile": name, "count": len(case[name]),
                   "complete": case["complete"] if name == "grave" else True,
                   **({"cards": [{"card_id": x} for x in case[name]]}
                      if name != "grave" or case["complete"] else {})}
                  for name in ("draw", "grave", "excluded")]
        assumptions.update(closed_draw_probe={"groups": groups, "draw_order": "unknown",
                           "time": "immediately before the tested draw; all prior discards already included"},
                           ordinary_next_turn_draw=3, target="target")
        remaining = 2
        text = "パラメータ+10"
        expected = "play:0"  # Wiring probe only; no optimal action oracle for cycle cases.
    else:
        remaining = case["remaining_turns"]
        text = "パラメータ+10 レッスン中1回"
        expected = case["expected"]
        assumptions.update(current_badge=10, future_actions="only the current one-shot card, else skip",
                           no_other_rewards=True, hp_recovery_has_no_future_value=True,
                           exact_confirmed_future_badge=case["future_score"],
                           confirmed_growth_effect="Installed conditional score modifier: next turn this one-shot scores 30 instead of its current 10; no other rewards or modifiers",
                           confirmed_next_turn_growth_and_return=(remaining == 2),
                           return_premise="If unused now, the card and at most one unavailable filler enter an otherwise empty discard and empty draw pile; ordinary next draw3 includes both. No retained hand or draw modifiers.")
    hand = [_card("a", int(swapped), "cycle", text, 10)]
    if swapped:
        hand.insert(0, _card("b", 0, "cycle", "パラメータ+1", 1, available=False))
        expected = expected.replace("play:0", "play:1")
    state = BattleState("synthetic-cycle", 1, remaining, 30, 30, 0, hand,
                        actions_left=1, motivation=0, impression=0, score=0,
                        multiplier_permil=1000, public_info="人工封闭前提：" + json.dumps(assumptions, ensure_ascii=False))
    memory = ExamMemory("synthetic-cycle", turn=1, last_remaining=remaining, actions_left=1)
    flags = {key: key == "HIRO_EXPLICIT_IDOL_STATE" for key in EXAM_REPLAY_FLAGS}
    advisor = RuleLLMAdvisor.__new__(RuleLLMAdvisor)
    advisor.profile = None
    with replay._flags(flags):
        frozen = freeze_exam_decision_input(state, memory,
            [Action.from_legal(x) for x in state.legal_actions()], [],
            advisor=advisor, source=SyntheticSource(), idol_card_id=None)
    return frozen["input"], expected, assumptions


def build_cases():
    result = []
    for case in CASES["choice_cases"]:
        for swapped in (False, True):
            payload, expected, assumptions = freeze(case, swapped=swapped)
            result.append({"id": case["id"] + f"/swap-{int(swapped)}", "input": payload,
                           "input_sha256": generic._hash(payload), "assumptions": assumptions,
                           "oracle": {"expected_action": expected, "plan": []},
                           "oracle_sha256": generic._hash({"expected_action": expected, "plan": []})})
    return result


def judge(decision, case):
    if not decision:
        return None
    action = Action.from_dict(decision["action"]).legal_key()
    legal = {Action.from_dict(a).legal_key() for a in case["input"]["legal"]}
    return {"legal": action in legal,
            "criterion_pass": action in legal and action == case["oracle"]["expected_action"]
                              and not decision.get("plan")}


def versions():
    result = replay._versions()
    for name in ("tools/check_synthetic_card_cycle.py", "examples/cases/card-cycle.json"):
        result["sha256_by_file"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    return result


def run(*, adapter=None, max_model_calls=0):
    if type(max_model_calls) is not int or not 0 <= max_model_calls <= 20:
        raise ValueError("cap must be 0..20")
    if adapter and max_model_calls == 0:
        raise ValueError("adapter requires explicit positive global cap")
    if adapter and not (adapter == "codex" or adapter.startswith(("codex:", "openai:"))):
        raise ValueError("adapter must be codex[:model] or openai:model")
    before = versions()
    capped = replay.CappedAdapter(from_spec(adapter), max_model_calls) if adapter else None
    results = []
    for case in build_cases():
        with replay._flags(case["input"]["flags"]):
            baseline = replay._decide(copy.deepcopy(case["input"]))
            used_before = capped.used if capped else 0
            model = replay._decide(copy.deepcopy(case["input"]), capped) if capped and capped.used < max_model_calls else None
        used = capped.used - used_before if capped else 0
        real = bool(capped and capped.name in ("codex-cli", "openai"))
        direct = bool(real and used == 1 and model and model.get("source") == "llm")
        evidence = copy.deepcopy(model.get("llm") or []) if model and used else []
        first = generic.first_model_choice(evidence)
        results.append({**case, "rule_baseline": baseline, "rule_checks": judge(baseline, case),
            "model_decision": model, "model_calls_used": used,
            "model_quality_status": "not_measured" if not used else "mock_adapter_not_quality" if not real
                else "direct_model" if direct else "guarded_or_requeried_pipeline_only",
            "direct_model_checks": judge(model, case) if direct else None,
            "pipeline_checks": judge(model, case) if used else None,
            "first_model_choice": first,
            "first_model_checks": judge(first["decision"], case) if real and first and first["decision"] else None,
            "model_call_evidence": evidence})
    after = versions()
    return {"scope": "closed_public_synthetic/real_generic_pipeline/not_game_simulator",
            "cases": results, "cycle_membership": [{"id": c["id"], "result": cycle_oracle(c)} for c in CASES["cycle_cases"]],
            "max_model_calls": max_model_calls, "model_calls_used": capped.used if capped else 0,
            "versions_start": before, "versions_end": after, "sources_changed_during_run": before != after,
            "limits": ["Artificial exact conditional future modifier and return premises; no real game reachability claim.",
                       "Cycle cases have membership oracles only; no optimal-action or probability claim.",
                       "Mock/guard success is not model quality; first response retained separately."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter")
    parser.add_argument("--max-model-calls", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(adapter=args.adapter, max_model_calls=args.max_model_calls)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(report["cases"]), "model_calls_used": report["model_calls_used"], "output": str(args.output)}))


if __name__ == "__main__":
    main()

