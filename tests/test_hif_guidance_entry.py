from types import SimpleNamespace
import pytest
from hiro.contracts import Action, ActionKind, Decision, GameState
from hiro.produce.hif import HiroHifStrategy


def test_uncertain_guidance_entry_does_not_choose_stale_alternative(monkeypatch):
    monkeypatch.delenv("HIRO_WINDOWS_HUD_NATIVE_SCALE", raising=False)
    obj = object.__new__(HiroHifStrategy)
    obs = SimpleNamespace(fields={"stamina": 37, "produce_point":760, "params":{}, "options":[]})
    calls = []
    obj.s = SimpleNamespace(state=GameState(), observe_complete=lambda *a:obs,
                            record=lambda *a, **k:None)
    obj._maybe_review_deck = lambda:None
    decision = Decision(Action(ActionKind.PRODUCE_NEXT, {"option":"special_guidance"}), "chosen", "rule", .9)
    obj.deciders = SimpleNamespace(decide=lambda *a:(calls.append("decide") or decision))
    obj._special_guidance = lambda o:False
    def stop(*a, **k):
        raise RuntimeError("uncertain entry stopped")
    obj._stop = stop
    def stale_action(*a):
        pytest.fail("must not translate old candidates after an uncertain entry")
    obj._to_produce_action = stale_action
    ctx = SimpleNamespace(fetch_available_actions=lambda:([], []))
    with pytest.raises(RuntimeError, match="uncertain entry stopped"):
        obj.on_action_select(ctx)
    assert calls == ["decide"]
