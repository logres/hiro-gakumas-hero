"""A resumed trace must replay from the seed injected before its first observation."""

import json

from hiro.contracts import GameState, Observation, PageObs, Source, Step, TraceWriter
from hiro.loop.replay import report, run


def _obs(seq=1):
    return Observation(seq=seq, t=1.0, page=PageObs("ACTION_SELECT", "produce"),
                       fields={"stamina": 33})


def _seed(seq=7):
    return GameState(mode="produce", produce={"mode": "produce-007", "step": 5, "stamina": 34},
                     sources={f"produce.{key}": Source("infer", seq) for key in ("mode", "step", "stamina")})


def _write_step(writer, seed):
    obs = _obs()
    final = run([[obs]], initial=seed)[0]
    writer.write(Step(seq=1, t=1.0, observation=obs, state=final))
    writer.close()
    return final


def test_snapshot_before_first_step_replays_and_is_recorded(tmp_path):
    writer = TraceWriter(root=tmp_path, name="run-r1", meta={"command": "resume"})
    seed = _seed()
    writer.record_initial_state(seed)
    expected = _write_step(writer, seed)
    metadata = json.loads((writer.dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["initial_states"] == [{"first_seq": 1, "state": seed.to_dict()}]
    result = report(writer.dir / "steps.jsonl")
    assert result["deterministic"] and result["state_mismatch_vs_trace"] == []
    assert expected.conflicts  # infer=34 vs screen=33 is part of the replayed state


def test_old_resume_uses_previous_segment_only(tmp_path):
    prior = TraceWriter(root=tmp_path, name="run")
    prior.write(Step(seq=7, t=0.0, observation=_obs(7), state=GameState(
        mode="produce", produce={"mode": "produce-007", "step": 5, "stamina": 34})))
    prior.close()
    current = TraceWriter(root=tmp_path, name="run-r1", meta={"command": "resume"})
    _write_step(current, _seed())
    result = report(current.dir / "steps.jsonl")
    assert result["deterministic"] and result["state_mismatch_vs_trace"] == []


def test_old_resume_without_prior_does_not_trust_own_recorded_state(tmp_path):
    current = TraceWriter(root=tmp_path, name="run-r1", meta={"command": "resume"})
    _write_step(current, _seed())
    assert report(current.dir / "steps.jsonl")["state_mismatch_vs_trace"] == [1]
