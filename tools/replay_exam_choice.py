"""Replay one complete, frozen HIF_EXAM decision input without touching the game.

Old traces without exam_decision_input are deliberately rejected. A comparison
of one decision does not establish a score improvement over an entire exam.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path

from hiro.brain.cards import CardTags, CardView, DrinkView
from hiro.brain.llm import LLMResult, from_spec
from hiro.brain.state import BattleState, ExamMemory, IdolProfile, Installed
from hiro.contracts import Action, Preview
from hiro.contracts.trace import EXAM_REPLAY_FLAGS
from hiro.defaults.advisor import RuleLLMAdvisor

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = (
    "src/hiro/brain/battle.py", "src/hiro/brain/rules.py", "src/hiro/brain/state.py",
    "src/hiro/brain/cards.py", "src/hiro/produce/exam_policy.py", "src/hiro/defaults/advisor.py",
    "src/hiro/brain/fallback_drinks.py", "src/hiro/brain/route_policy.py",
    "src/hiro/brain/plan_evidence.py",
    "src/hiro/brain/fallback_effect_scoring.py",
    "src/hiro/brain/active_card_context.py", "src/hiro/defaults/exam_state.py",
    "src/hiro/brain/active_drink_context.py",
    "src/hiro/brain/status_evidence_context.py",
    "src/hiro/brain/exam_deck_context.py", "src/hiro/brain/mechanism_card_selection.py",
    "src/hiro/brain/prompts/exam.md", "src/hiro/brain/prompts/exam_generic.md",
    "src/hiro/brain/strategy_references.py", "src/hiro/defaults/strategy_refs/review_engine_action.json",
)
FLAGS = EXAM_REPLAY_FLAGS


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _require_keys(value: dict, cls: type, label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 不是对象")
    expected = {f.name for f in fields(cls)}
    if set(value) != expected:
        raise ValueError(f"{label} 字段不完整或未知：缺 {sorted(expected - set(value))}，多 {sorted(set(value) - expected)}")


def _load(trace: Path, seq: int) -> tuple[Path, dict, dict]:
    path = trace / "steps.jsonl" if trace.is_dir() else trace
    if path.name != "steps.jsonl" or not path.is_file() or seq < 1:
        raise ValueError("需要 trace 目录或 steps.jsonl，以及正整数 --seq")
    matches = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("seq") == seq:
                matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"seq {seq} 匹配 {len(matches)} 帧；需要恰好一帧")
    step = matches[0]
    if ((step.get("observation") or {}).get("page") or {}).get("name") != "HIF_EXAM" or not step.get("decision"):
        raise ValueError(f"seq {seq} 不是有记录决策的 HIF_EXAM 帧")
    frozen = step.get("exam_decision_input")
    if not isinstance(frozen, dict) or frozen.get("schema_version") != "1.0":
        raise ValueError("旧 trace 缺少完整考试决策前快照；GameState/exam_memory.json 无法无损重建 BattleState 和 ExamMemory")
    payload = frozen.get("input")
    if not isinstance(payload, dict) or hashlib.sha256(_canonical(payload)).hexdigest() != frozen.get("sha256"):
        raise ValueError("考试输入快照 hash 不符或内容缺失")
    expected = {"battle_state", "exam_memory", "legal", "previews", "profile", "advisor", "source",
                "source_confidence", "idol_card_id", "flags"}
    if set(payload) != expected:
        raise ValueError(f"考试输入快照字段不完整：{sorted(expected - set(payload))}")
    if payload["advisor"] != "hiro.defaults.advisor.RuleLLMAdvisor":
        raise ValueError(f"不支持重放自定义 advisor {payload['advisor']}")
    return path, step, frozen


def _state(payload: dict) -> tuple[BattleState, ExamMemory, IdolProfile | None, list[Preview], list[Action]]:
    raw = copy.deepcopy(payload["battle_state"])
    _require_keys(raw, BattleState, "BattleState")
    for card in raw["hand"]:
        _require_keys(card, CardView, "CardView")
        _require_keys(card["tags"], CardTags, "CardTags")
    for drink in raw["drinks"]:
        _require_keys(drink, DrinkView, "DrinkView")
    for installed in raw["installed"]:
        _require_keys(installed, Installed, "Installed")
    raw["hand"] = [CardView.from_dict(card) for card in raw["hand"]]
    raw["drinks"] = [DrinkView.from_dict(drink) for drink in raw["drinks"]]
    raw["installed"] = [Installed(**item) for item in raw["installed"]]
    if raw["trend"] is not None:
        raw["trend"] = tuple(raw["trend"])
    state = BattleState(**raw)
    _require_keys(payload["exam_memory"], ExamMemory, "ExamMemory")
    for installed in payload["exam_memory"]["installed"]:
        _require_keys(installed, Installed, "ExamMemory.installed")
    memory = ExamMemory.from_dict(copy.deepcopy(payload["exam_memory"]))
    profile_data = payload["profile"]
    if profile_data is not None:
        _require_keys(profile_data, IdolProfile, "IdolProfile")
    profile = IdolProfile(**copy.deepcopy(profile_data)) if profile_data is not None else None
    if not isinstance(payload["legal"], list) or not isinstance(payload["previews"], list):
        raise ValueError("legal/previews 缺失")
    legal = [Action.from_dict(row) for row in payload["legal"]]
    previews = [Preview.from_dict(row) for row in payload["previews"]]
    if {a.legal_key() for a in legal} != set(state.legal_actions()):
        raise ValueError("冻结的 legal 与 BattleState 不一致")
    return state, memory, profile, previews, legal


@contextmanager
def _flags(saved: dict):
    # Schema 1.0 inputs recorded before this opt-in existed used legacy plans.
    saved = {"HIRO_PLAN_EFFECT_REVALIDATION": False, "HIRO_FALLBACK_EFFECT_SCORING": False,
             "HIRO_ACTIVE_CARD_EFFECT_CONTEXT": False, "HIRO_ACTIVE_DRINK_EFFECT_CONTEXT": False,
             "HIRO_EXAM_DECK_CONTEXT": False, "HIRO_TYPED_STATUS_CONTEXT": False, **saved}
    if set(saved) != set(FLAGS) or any(type(v) is not bool for v in saved.values()):
        raise ValueError("策略 flags 缺失或无效")
    old = {name: os.environ.get(name) for name in (*FLAGS, "HIRO_LLM")}
    try:
        for name in FLAGS:
            os.environ[name] = "1" if saved[name] else "0"
        os.environ.pop("HIRO_LLM", None)
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class CappedAdapter:
    def __init__(self, inner, maximum: int):
        self.inner, self.maximum, self.used = inner, maximum, 0
        self.name, self.model = inner.name, inner.model

    def ask_json(self, system: str, user: str):
        if self.used >= self.maximum:
            return LLMResult(None, "", 0.0, "replay model call limit reached", self.name, self.model)
        self.used += 1
        return self.inner.ask_json(system, user)


def _decide(payload: dict, adapter=None) -> dict:
    state, memory, profile, previews, legal = _state(payload)
    advisor = RuleLLMAdvisor(profile, llm=adapter)
    return advisor.decide(state, memory, previews, legal).to_dict()


def _versions() -> dict:
    names = (*VERSION_FILES, *(str(path.relative_to(ROOT)).replace("\\", "/")
                              for path in sorted((ROOT / "src/hiro/brain/prompts/idols").glob("*.md"))))
    hashed = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() if (ROOT / name).is_file() else None
              for name in names}
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=3, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    return {"git_head": head, "sha256_by_file": hashed}


def compare(trace: Path, seq: int, *, adapter: str | None = None, max_model_calls: int = 3) -> dict:
    if adapter and not (adapter == "codex" or adapter.startswith("codex:") or adapter.startswith("openai:")):
        raise ValueError("--adapter 仅接受 codex[:model] 或 openai:model")
    if not 1 <= max_model_calls <= 10:
        raise ValueError("--max-model-calls 须在 1..10")
    path, step, frozen = _load(trace, seq)
    payload = frozen["input"]
    # Validate both independent copies before any model invocation.
    _state(payload)
    with _flags(payload["flags"]):
        baseline = _decide(copy.deepcopy(payload))
        capped = CappedAdapter(from_spec(adapter), max_model_calls) if adapter else None
        model = _decide(copy.deepcopy(payload), capped) if capped else None
    legal = {Action.from_dict(a).legal_key() for a in payload["legal"]}
    original = step["decision"]
    result = {"scope": "单帧完整冻结局面对照；不证明考试分数提升", "trace": str(path), "seq": seq,
              "input_schema": frozen["schema_version"], "input_sha256": frozen["sha256"],
              "battle_state_sha256": hashlib.sha256(_canonical(payload["battle_state"])).hexdigest(),
              "exam_memory_sha256": hashlib.sha256(_canonical(payload["exam_memory"])).hexdigest(),
              "identity": payload["idol_card_id"], "flags": payload["flags"], "versions": _versions(),
              "state_summary": {"exam": payload["battle_state"]["exam"], "turn": payload["battle_state"]["turn"],
                                "remaining_turns": payload["battle_state"]["remaining_turns"],
                                "hp": payload["battle_state"]["hp"], "score": payload["battle_state"]["score"],
                                "hand": [c["name"] for c in payload["battle_state"]["hand"]],
                                "drinks": [d["name"] for d in payload["battle_state"]["drinks"]]},
              "strategy_references": payload["battle_state"]["strategy_references"],
              "recorded": original, "recorded_legal": Action.from_dict(original["action"]).legal_key() in legal,
              "rule_baseline": baseline, "rule_baseline_legal": Action.from_dict(baseline["action"]).legal_key() in legal,
              "model_adapter": adapter, "max_model_calls": max_model_calls,
              "model_calls_used": capped.used if capped else 0, "model_decision": model,
              "model_legal": Action.from_dict(model["action"]).legal_key() in legal if model else None,
              "limits": ["仅读取指定 seq 的决策前快照；不读取 state_after、未来帧或设备",
                         "当前代码与提示词 hash 可能不同于记录时；记录的原始 LLM 回复仅作历史证据"]}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="trace 目录或 steps.jsonl")
    parser.add_argument("--seq", type=int, required=True, help="只对照这一帧")
    parser.add_argument("--adapter", help="显式启用模型：codex[:model] 或 openai:model")
    parser.add_argument("--max-model-calls", type=int, default=3, help="本次决策链最多实际调用模型的次数，默认 3")
    args = parser.parse_args(argv)
    try:
        result = compare(args.trace, args.seq, adapter=args.adapter, max_model_calls=args.max_model_calls)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
