"""离线重放：Observation 序列 → GameState 序列，校验确定性与页面稳定性。

    python -m hiro.loop.replay reports/contracts/<数据集>-observations.jsonl [--out reports/replay/<名>.jsonl]
    python -m hiro.loop.replay traces/<run>/steps.jsonl           # 用 trace 里的 observation 重放并与记录的 state 比对

输出：每行 {seq, page, mode, changed_keys}；统计：页面切换次数、抖动次数（A→B→A 且 B 停留 < DEBOUNCE 帧）、
两次重放是否逐帧一致、与 trace 记录的 state 不一致的帧数。
"""

import argparse
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from hiro.contracts import GameState, Observation, Source, Step
from hiro.loop.reduce import DEBOUNCE, reduce


def load_observations(path: Path) -> tuple[list[list[Observation]], list[GameState | None]]:
    """observations.jsonl 或 steps.jsonl → (观测组, 每组结束时记录的状态或 None)。

    数据集样本一帧一组；trace 的一步一组：observations_before + observation + observations_after。"""
    groups, recorded = [], []
    load_observations.events = []  # 每组的事件（1.2）；数据集样本为空
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if "observation" in d:
                step = Step.from_dict(d)
                groups.append([*step.observations_before, step.observation, *step.observations_after])
                recorded.append(step.state_after or step.state)  # 组末状态；1.1 起 state 是决策输入
                load_observations.events.append(list(step.events))
            else:
                groups.append([Observation.from_dict(d)])
                recorded.append(None)
                load_observations.events.append([])
    return groups, recorded


def run(groups: list[list[Observation]] | list[Observation], initial: GameState | None = None, events: list[list] | None = None,
        initial_states: dict[int, GameState] | None = None) -> list[GameState]:
    """逐组走主循环同一条路径（互验 → reduce → 事件），返回每组结束时的状态。也接受扁平的 Observation 列表。"""
    from hiro.loop.events import apply_event, reduce_checked, settle

    s = initial or GameState()
    preds: list = []
    out = []
    for i, g in enumerate(groups):
        first = g[0] if isinstance(g, list) else g
        if initial_states and first.seq in initial_states:
            s = initial_states[first.seq]
            preds = []  # a new Session starts with no pending predictions
        for o in (g if isinstance(g, list) else [g]):
            s, checks = reduce_checked(s, o, preds)
            preds = settle(preds, checks)
        for ev in (events[i] if events and i < len(events) else []):
            s, p = apply_event(s, ev)
            preds.extend(p)
        out.append(s)
    return out


def _legacy_resume_seed(path: Path) -> GameState | None:
    """Recover the pre-first-step seed of old -rN traces from preceding segments.

    Mirrors HiroHifStrategy._seed_produce_from_trace; never takes the current
    segment's recorded state as an initial state for its own comparison.
    """
    match = re.fullmatch(r"(.+)-r(\d+)", path.parent.name)
    if not match:
        return None
    base, index = match.group(1), int(match.group(2))
    last, last_seq = None, 0
    for d in sorted(path.parent.parent.glob(base + "*")):
        prior = re.fullmatch(re.escape(base) + r"(?:-r(\d+))?", d.name)
        if not prior or (int(prior.group(1)) if prior.group(1) else 0) >= index:
            continue
        try:
            with (d / "steps.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        step = json.loads(line)
                    except ValueError:
                        continue
                    state = step.get("state_after") or step.get("state") or {}
                    if state.get("produce"):
                        last, last_seq = state, int(step.get("seq") or 0)
        except OSError:
            continue
    if last is None:
        return None
    produce = last["produce"]
    return replace(GameState(), produce=produce,
                   sources={f"produce.{key}": Source("infer", last_seq) for key in produce},
                   mode=last.get("mode", "unknown"))


def _initial_states(path: Path, groups: list[list[Observation]]) -> dict[int, GameState]:
    if path.name != "steps.jsonl" or not groups:
        return {}
    run_path = path.parent / "run.json"
    try:
        meta = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    snapshots = {int(entry["first_seq"]): GameState.from_dict(entry["state"])
                 for entry in meta.get("initial_states", [])}
    first_seq = groups[0][0].seq
    if first_seq not in snapshots and meta.get("command") == "resume":
        if seed := _legacy_resume_seed(path):
            snapshots[first_seq] = seed
    return snapshots


def flaps(states: list[GameState]) -> list[tuple[int, str, str]]:
    """A→B→A 且 B 停留不足 DEBOUNCE 帧的切换。"""
    seq = []
    for st in states:
        if not seq or seq[-1][1] != st.page.name:
            seq.append([st.seq, st.page.name, 1])
        else:
            seq[-1][2] += 1
    out = []
    for i in range(1, len(seq) - 1):
        if seq[i - 1][1] == seq[i + 1][1] and seq[i][2] < DEBOUNCE:
            out.append((seq[i][0], seq[i - 1][1], seq[i][1]))
    return out


def report(path: Path, out: Path | None = None) -> dict:
    observations, recorded = load_observations(path)
    evs = getattr(load_observations, "events", None)
    initial_states = _initial_states(path, observations)
    a = run(observations, events=evs, initial_states=initial_states)
    b = run(observations, events=evs, initial_states=initial_states)
    identical = all(x.to_dict() == y.to_dict() for x, y in zip(a, b)) and len(a) == len(b)
    changes = sum(1 for i in range(1, len(a)) if a[i].page.name != a[i - 1].page.name)
    mismatch = [st.seq for st, rec in zip(a, recorded) if rec is not None and st.to_dict() != rec.to_dict()]
    fl = flaps(a)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            prev = None
            for g, st in zip(observations, a):
                o = g[-1]
                changed = sorted(k for k, v in st.sources.items() if v.seq == o.seq)
                row = {"seq": o.seq, "obs_page": o.page.name, "page": st.page.name, "stable": st.page.stable, "mode": st.mode,
                       "pending": st.pending_page.name if st.pending_page else None, "changed": changed,
                       "turn": st.exam_session.turn if st.page.name == "HIF_EXAM" else None}  # fmt: skip
                if prev is None or row["page"] != prev["page"] or changed or row["pending"] != prev["pending"]:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                prev = row
            f.write(json.dumps({"final_state": a[-1].to_dict()}, ensure_ascii=False) + "\n")
    return {
        "input": str(path), "frames": len(a), "deterministic": identical, "page_changes": changes, "flaps": fl,
        "pending_accepts": [c for c in a[-1].conflicts if "不在转移图" in c][:10], "conflicts": len(a[-1].conflicts),
        "state_mismatch_vs_trace": mismatch[:20], "final_page": a[-1].page.name, "final_mode": a[-1].mode,
        "final_produce": a[-1].produce, "out": str(out) if out else None,
    }  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    out = args.out or Path("reports/replay") / (args.path.parent.name if args.path.name == "steps.jsonl" else args.path.stem).replace("-observations", "") 
    out = out.with_suffix(".jsonl")
    r = report(args.path, out)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0 if r["deterministic"] and not r["flaps"] and not r["state_mismatch_vs_trace"] else 1


if __name__ == "__main__":
    sys.exit(main())
