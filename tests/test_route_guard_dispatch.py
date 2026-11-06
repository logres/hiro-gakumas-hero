"""A route decision must never be replaced by a specialist fallback."""

import pytest

from hiro.brain.deciders import ProduceDeciders
from hiro.contracts import Action, ActionKind, Decision, GameState


@pytest.mark.parametrize("failure", [False, True])
def test_route_wait_does_not_fall_back_to_study_template(monkeypatch, failure):
    from hiro.brain import route_guard

    def guarded(*args, **kwargs):
        if failure:
            raise KeyError("missing route data")
        return Decision(Action.ui(ActionKind.WAIT, why="unknown choices"), "unknown choices", "rule", .1)

    monkeypatch.setattr(route_guard, "guard", guarded)
    decider = ProduceDeciders(None)
    monkeypatch.setattr(decider, "study", lambda *a: pytest.fail("legacy study must not run"))
    monkeypatch.setattr(decider, "_page_fallback", lambda *a, **k: pytest.fail("legacy fallback must not run"))
    assert decider.decide("STUDY", GameState(), n_options=3).action.kind is ActionKind.WAIT


def test_route_choice_still_checks_visible_option_bounds(monkeypatch):
    from hiro.brain import route_guard

    monkeypatch.setattr(route_guard, "guard", lambda *a, **k:
                        Decision(Action.event_select(4), "observed choice", "rule", .8))
    result = ProduceDeciders(None).decide("STUDY", GameState(), n_options=3)
    assert result.action.kind is ActionKind.WAIT
    assert "route_policy_skip" in result.warnings
