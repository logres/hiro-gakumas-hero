"""Compare one recorded SELECT_CARD decision with today's rules and opt-in mechanism.

This is a frozen-state comparison. It never opens a device or executes an action.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from hiro.brain.deciders import ProduceDeciders
from hiro.brain.llm import from_spec
from hiro.contracts import GameState

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = ("src/hiro/brain/deciders.py", "src/hiro/brain/mechanism_card_selection.py",
                 "src/hiro/brain/prompts/mechanism_card_pick.md", "src/hiro/brain/route_guard.py",
                 "src/hiro/brain/route_policy.py", "src/hiro/brain/review_card_roles.py",
                 "src/hiro/brain/cards.py", "src/hiro/brain/hif_rules.py")


def _trace_path(path: Path) -> Path:
    result = path / "steps.jsonl" if path.is_dir() else path
    if result.name != "steps.jsonl" or not result.is_file():
        raise ValueError("输入须为 trace 目录或其中的 steps.jsonl")
    return result


def _frame(path: Path, seq: int) -> dict:
    if seq < 1:
        raise ValueError("--seq 须为正整数")
    matches = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                step = json.loads(line)
            except json.JSONDecodeError:
                continue  # 正在写入的最后一行不能当成完整记录
            if step.get("seq") == seq:
                matches.append(step)
    if len(matches) != 1:
        raise ValueError(f"seq {seq} 匹配 {len(matches)} 帧；需要恰好一帧")
    step = matches[0]
    def usable_version(value):
        try:
            major, minor = (int(part) for part in str(value).split(".", 1))
            return (major, minor) >= (1, 1)
        except (ValueError, TypeError):
            return False

    if not usable_version(step.get("version")) or not usable_version((step.get("state") or {}).get("version")):
        raise ValueError(f"seq {seq} 的 trace/state 契约早于 1.1 或未知；旧 trace 的 state 可能是执行后态")
    page = ((step.get("observation") or {}).get("page") or {}).get("name")
    state = step.get("state") or {}
    state_page = (state.get("page") or {}).get("name")
    if page != "SELECT_CARD" or state_page != "SELECT_CARD":
        raise ValueError(f"seq {seq} 不是已稳定的 SELECT_CARD 决策输入（观测 {page}，状态 {state_page}）")
    if not isinstance(((step.get("decision") or {}).get("action")), dict):
        raise ValueError(f"seq {seq} 没有记录原决策动作，不能作单帧对照")
    if not isinstance((state.get("page_fields") or {}).get("candidates"), list):
        raise ValueError(f"seq {seq} 的 state.page_fields.candidates 未记录，不能补猜")
    return step


def _identity(trace: Path, explicit: str | None) -> tuple[str, str]:
    if explicit:
        return explicit, "--idol"
    run_file = trace.parent / "run.json"
    if run_file.is_file():
        run = json.loads(run_file.read_text(encoding="utf-8"))
        idol = run.get("idol")
        if isinstance(idol, str) and idol:
            return idol, "run.json:idol"
    raise ValueError("run.json 没有偶像身份；请显式传 --idol")


def _versions() -> dict:
    files = {}
    for name in VERSION_FILES:
        path = ROOT / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=3, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    return {"git_head": head, "sha256_prefix_by_file": files}


def _summary(state: GameState) -> dict:
    produce = state.produce or {}
    deck = produce.get("deck")
    return {"mode": produce.get("mode"), "step": produce.get("step"), "stamina": produce.get("stamina"),
            "produce_point": produce.get("produce_point"), "params": produce.get("params"),
            "deck_recorded_count": len(deck) if isinstance(deck, list) else None,
            "deck_recorded_size": produce.get("deck_size"),
            "deck_source": getattr(state.sources.get("produce.deck"), "origin", None),
            "deck_field_status": state.field_status.get("produce.deck"),
            "candidates": state.page_fields.get("candidates"),
            "recommended": state.page_fields.get("recommended"),
            "rerolls_left": state.page_fields.get("rerolls_left"),
            "excludes_left": state.page_fields.get("excludes_left")}


def compare(trace: Path, seq: int, *, idol: str | None = None, adapter: str | None = None) -> dict:
    path = _trace_path(trace)
    step = _frame(path, seq)
    identity, identity_source = _identity(path, idol)
    recorded = step["state"]
    state_identity = (recorded.get("produce") or {}).get("idol_card_id")
    if state_identity and state_identity.replace("i_card-skin-", "i_card-") != identity.replace("i_card-skin-", "i_card-"):
        raise ValueError(f"state.produce.idol_card_id={state_identity} 与 {identity_source}={identity} 不同；拒绝替换输入")
    frame_json = json.dumps({"seq": seq, "state": recorded}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    summary = _summary(GameState.from_dict(copy.deepcopy(recorded)))
    n_options = len(recorded["page_fields"]["candidates"])
    if adapter and not (adapter == "codex" or adapter.startswith("codex:") or adapter.startswith("openai:")):
        raise ValueError("--adapter 仅接受 codex[:model] 或 openai:model")

    # Run each comparison with a fresh decider. No earlier hidden picked_musts
    # or off-screen history is reconstructed from later trace frames.
    old_route = os.environ.get("HIRO_EXPLICIT_IDOL_STATE")
    old_mechanism = os.environ.get("HIRO_MECHANISM_CARD_SELECTION")
    policy_flags = {"HIRO_REVIEW_FIRST_EXAM_ROLES": os.environ.get("HIRO_REVIEW_FIRST_EXAM_ROLES") == "1",
                    "baseline": {"HIRO_EXPLICIT_IDOL_STATE": True, "HIRO_MECHANISM_CARD_SELECTION": False},
                    "mechanism": {"HIRO_EXPLICIT_IDOL_STATE": True, "HIRO_MECHANISM_CARD_SELECTION": True}}
    try:
        os.environ["HIRO_EXPLICIT_IDOL_STATE"] = "1"
        os.environ["HIRO_MECHANISM_CARD_SELECTION"] = "0"
        baseline = ProduceDeciders(None, None, idol_card_id=identity).decide(
            "SELECT_CARD", GameState.from_dict(copy.deepcopy(recorded)), n_options=n_options)
        os.environ["HIRO_MECHANISM_CARD_SELECTION"] = "1"
        mechanism = ProduceDeciders(None, from_spec(adapter) if adapter else None, idol_card_id=identity).decide(
            "SELECT_CARD", GameState.from_dict(copy.deepcopy(recorded)), n_options=n_options)
    finally:
        for key, value in (("HIRO_EXPLICIT_IDOL_STATE", old_route), ("HIRO_MECHANISM_CARD_SELECTION", old_mechanism)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    original = step["decision"]
    return {"scope": "单帧冻结局面对照；不是分数提升或整局策略优劣证明", "trace": str(path), "seq": seq,
            "input_state_sha256": hashlib.sha256(frame_json).hexdigest(),
            "identity": {"idol": identity, "source": identity_source}, "adapter": adapter,
            "state_summary": summary, "recorded_action": original["action"],
            "recorded_source": original.get("source"), "recorded_reason": original.get("reason"),
            "rule_baseline": baseline.to_dict(), "mechanism": mechanism.to_dict(),
            "versions": _versions(), "policy_flags": policy_flags,
            "limits": ["仅使用该步 state；未读取 state_after、后续帧或设备", "未重建 trace 未记录的 picked_musts / seen_deck 等隐含决策器状态",
                       "未知牌组完整性、卡牌定制及未记录观测仍保持未知"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="trace 目录或 steps.jsonl")
    parser.add_argument("--seq", type=int, required=True, help="只对照这一帧")
    parser.add_argument("--idol", help="明确身份；默认读取同目录 run.json:idol")
    parser.add_argument("--adapter", help="显式启用模型：codex[:model] 或 openai:model")
    args = parser.parse_args(argv)
    try:
        result = compare(args.trace, args.seq, idol=args.idol, adapter=args.adapter)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
