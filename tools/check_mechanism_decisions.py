"""Small hypothetical, real-master-data exam acceptance set. Never opens a device.

Default: rule baseline and input/oracle audit only. An explicit adapter measures
model-assisted decisions with one global call limit. No result implies an exam
score improvement, reachable recorded game state, or automatic strategy learning.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hiro.brain.cards import CardView, description_text, parse_tags
from hiro.brain.llm import from_spec
from hiro.brain.state import BattleState, ExamMemory
from hiro.contracts import Action
from hiro.contracts.trace import EXAM_REPLAY_FLAGS, freeze_exam_decision_input
from hiro.defaults.advisor import RuleLLMAdvisor
from hiro.state.catalog import catalog
from tools import replay_exam_choice as replay

IDENTITIES = (
    ("i_card-kllj-3-000", "ExamReview"),
    ("i_card-atbm-2-000", "ExamReview"),
    ("i_card-fktn-3-002", "ExamCardPlayAggressive"),
    ("i_card-amao-3-001", "ExamLessonBuff"),
    ("i_card-atbm-1-000", "ExamConcentration"),
)
COMMON = "p_card-00-act-0_002"
REFUND = "p_card-02-men-2_060"
CASH = "p_card-02-act-2_046"
SPECS = {
    (COMMON, 0): ("ポーズの基本", "ProducePlanType_Common", "ProduceCardCategory_ActiveSkill", 3, "ExamCostType_Unknown", 0, "パラメータ+2元気+2", 0),
    (COMMON, 1): ("ポーズの基本+", "ProducePlanType_Common", "ProduceCardCategory_ActiveSkill", 3, "ExamCostType_Unknown", 0, "パラメータ+6元気+4", 0),
    (REFUND, 1): ("オトメゴコロ+", "ProducePlanType_Plan2", "ProduceCardCategory_MentalSkill", 0, "ExamCostType_ExamCardPlayAggressive", 3,
                  "やる気消費3好印象+5スキルカード使用数追加+1好印象が10以上の場合、好印象+2重複不可", 1),
    (CASH, 1): ("ラブリーウインク+", "ProducePlanType_Plan2", "ProduceCardCategory_ActiveSkill", 5, "ExamCostType_Unknown", 0,
                "好印象+5好印象の80%分パラメータ上昇", 0),
}


def _hash(value):
    return hashlib.sha256(replay._canonical(value)).hexdigest()


def _checked_cards(master):
    rows = {}
    for key, expected in SPECS.items():
        row = master.card(*key)
        actual = tuple(row.get(k) for k in ("name", "planType", "category", "stamina", "costType", "costValue"))
        actual += (description_text(row.get("produceDescriptions")), row.get("noDeckDuplication"))
        if (actual != expected or row.get("id") != key[0] or row.get("upgradeCount") != key[1]
                or row.get("forceStamina") != 0 or row.get("playProduceExamTriggerId") not in (None, "")
                or row.get("produceCardStatusEnchantId") not in (None, "")
                or row.get("playMovePositionType") != "ProduceCardMovePositionType_Grave"):
            raise ValueError(f"主数据改变，拒绝沿用支配判据：{key}")
        rows[key] = row
    return rows


def _view(row, slot, available=True):
    text = description_text(row["produceDescriptions"])
    extra = {"type": row["costType"], "value": row["costValue"]} if row["costValue"] else None
    return CardView(slot, row["name"], row["id"], row["upgradeCount"], available,
                    "active" if row["category"] == "ProduceCardCategory_ActiveSkill" else "mental",
                    row["stamina"], 0, extra, text, parse_tags(row["name"], text))


class _HypotheticalSource:
    def confidence(self):
        return "hypothetical_master_fixture"


def build_cases(master=None):
    """Reject changed master definitions before constructing any dominance claim."""
    master = master or catalog()
    rows = _checked_cards(master)
    cases = []
    flags = {key: key in ("HIRO_EXPLICIT_IDOL_STATE", "HIRO_FINAL_TURN_SETUP") for key in EXAM_REPLAY_FLAGS}
    for identity, mechanism in IDENTITIES:
        idol = master.one("IdolCard", identity)
        if idol.get("id") != identity or idol.get("examEffectType") != "ProduceExamEffectType_" + mechanism:
            raise ValueError(f"偶像主数据机制改变，拒绝沿用案例：{identity}")
        groups = [("equal_cost_upgrade", None)]
        if mechanism in ("ExamReview", "ExamCardPlayAggressive"):
            groups += [("refund_resource_positive", 3), ("refund_resource_negative", 2)]
        for group, motivation in groups:
            for swapped in (False, True):
                if group == "equal_cost_upgrade":
                    used = [(COMMON, 0), (COMMON, 1)]
                    hand = [_view(rows[key], i) for i, key in enumerate(used)]
                    expected_key = (COMMON, 1)
                    rationale = "末回合仅1行动；同费3、同类别，无其他触发。强化版即时参数+6严格高于+2，元气+4亦不低于+2。"
                else:
                    used = [(REFUND, 1), (CASH, 1)]
                    hand = [_view(rows[key], i, motivation >= 3 if key[0] == REFUND else True) for i, key in enumerate(used)]
                    expected_key = (REFUND, 1) if motivation >= 3 else (CASH, 1)
                    rationale = ("好印象20、やる気3；先支付3使好印象+7并返还1行动，再兑现，优于先耗尽唯一行动。无其他やる気用途或触发。"
                                 if motivation >= 3 else "やる気2不足支付明确的3消耗；返还行动不能先于支付。该牌不可用，仍可打出的兑现牌优于无收益跳过。")
                if swapped:
                    hand.reverse()
                    for i, card in enumerate(hand):
                        card.slot = i
                target = next(card for card in hand if (card.card_id, card.upgrade) == expected_key)
                assumptions = {
                    "kind": "hypothetical/not_recorded", "idol_card_id": identity,
                    "all_equipped_item_charges": 0, "other_triggers": [], "customization": False,
                    "concentration": 0, "good_condition": 0, "multiplier_permil": 1000,
                    "note": "人工构造验收局面，不是实机截图；所有额外触发/持续效果均假设不存在；无徽章读数。",
                }
                state = BattleState("qualify-3", 12, 1, 30, 40, 20, hand, impression=20,
                    motivation=motivation if motivation is not None else 0, actions_left=1,
                    multiplier_permil=1000, recommended_effect=idol["examEffectType"],
                    item_charges_left=0, source="hypothetical_master_fixture",
                    public_info="合成验收假设：" + json.dumps(assumptions, ensure_ascii=False))
                memory = ExamMemory("qualify-3", turn=12, last_remaining=1, actions_left=1, item_charges_left=0)
                advisor = RuleLLMAdvisor.__new__(RuleLLMAdvisor)
                advisor.profile = None
                with replay._flags(flags):
                    frozen = freeze_exam_decision_input(state, memory,
                        [Action.from_legal(a) for a in state.legal_actions()], [], advisor=advisor,
                        source=_HypotheticalSource(), idol_card_id=identity)
                replay._state(frozen["input"])
                oracle = {"expected_action": f"play:{target.slot}", "rationale": rationale,
                          "expected_followup": rows[(CASH, 1)]["name"] if group == "refund_resource_positive" else None}
                cases.append({"id": f"{group}/{identity}/swap-{int(swapped)}", "group": group,
                    "assumptions": assumptions, "oracle": oracle, "frozen": frozen,
                    "master_row_sha256": {f"ProduceCard:{cid}:{up}": _hash(rows[(cid, up)]) for cid, up in used}
                                          | {f"IdolCard:{identity}": _hash(idol)}})
    return cases


def judge(decision, case):
    key = Action.from_dict(decision["action"]).legal_key()
    legal = {Action.from_dict(a).legal_key() for a in case["frozen"]["input"]["legal"]}
    followup = case["oracle"]["expected_followup"]
    plan = decision.get("plan") or []
    # A reported correct first move does not demonstrate the required continuation.
    plan_ok = (len(plan) == 1 and isinstance(plan[0], dict) and plan[0].get("action") == "play"
               and plan[0].get("card") == followup) if followup else not plan
    return {"legal": key in legal, "expected_action": key == case["oracle"]["expected_action"],
            "required_plan": plan_ok, "criterion_pass": key in legal and key == case["oracle"]["expected_action"] and plan_ok}


def run(*, adapter=None, max_model_calls=8, case_ids=None, master=None):
    if not 1 <= max_model_calls <= 100:
        raise ValueError("global model call cap must be 1..100")
    if adapter and not (adapter == "codex" or adapter.startswith("codex:") or adapter.startswith("openai:")):
        raise ValueError("adapter must be codex[:model] or openai:model")
    cases = build_cases(master)
    if case_ids:
        unknown = set(case_ids) - {case["id"] for case in cases}
        if unknown:
            raise ValueError(f"unknown cases: {sorted(unknown)}")
        cases = [case for case in cases if case["id"] in case_ids]
    capped = replay.CappedAdapter(from_spec(adapter), max_model_calls) if adapter else None
    results = []
    for case in cases:
        payload = case["frozen"]["input"]
        with replay._flags(payload["flags"]):
            baseline = replay._decide(copy.deepcopy(payload))
            model = None
            before = capped.used if capped else 0
            if capped and capped.used < max_model_calls:
                model = replay._decide(copy.deepcopy(payload), capped)
            used = capped.used - before if capped else 0
        # Rules/trivial/plan decisions without a model call do not count as model quality.
        measured = (model is not None and used > 0 and model.get("source") == "llm"
                    and capped.name in ("codex-cli", "openai"))
        if used and capped.name not in ("codex-cli", "openai"):
            status = "mock_adapter_not_quality"
        elif used and model is not None and model.get("source") != "llm":
            status = "model_attempted_guarded"
        else:
            status = "measured" if measured else "not_measured"
        results.append({**case, "rule_baseline": baseline, "rule_checks": judge(baseline, case),
                        "model_decision": model, "model_calls_used": used,
                        "model_quality_status": status,
                        "model_checks": judge(model, case) if measured else None,
                        "model_assisted_pipeline_checks": judge(model, case) if model is not None and used else None,
                        "model_call_evidence": copy.deepcopy(model.get("llm") or []) if model is not None and used else []})
    versions = replay._versions()
    versions["sha256_by_file"]["tools/check_mechanism_decisions.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"scope": "显式假设的真实主数据机制验收；不是录制实机，不证明完整考试表现或自动学习。",
            "adapter": adapter, "global_max_model_calls": max_model_calls,
            "global_model_calls_used": capped.used if capped else 0, "versions": versions,
            "case_count": len(results), "model_measured_count": sum(r["model_quality_status"] == "measured" for r in results),
            "model_attempted_guarded_count": sum(r["model_quality_status"] == "model_attempted_guarded" for r in results),
            "cases": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter")
    parser.add_argument("--max-model-calls", type=int, default=8, help="global cap across all cases")
    parser.add_argument("--case", action="append", dest="case_ids", help="exact case ID; repeat to select")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(adapter=args.adapter, max_model_calls=args.max_model_calls, case_ids=args.case_ids)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"output": str(args.output), "case_count": report["case_count"],
                          "model_measured_count": report["model_measured_count"],
                          "global_model_calls_used": report["global_model_calls_used"]}, ensure_ascii=False))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
