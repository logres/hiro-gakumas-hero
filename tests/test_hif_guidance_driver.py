from types import SimpleNamespace
import pytest
from hiro.contracts import GameState
from hiro.produce.hif import HiroHifStrategy
from hiro.produce import guidance_session


def strategy():
    obj=object.__new__(HiroHifStrategy)
    obj.s=SimpleNamespace(state=GameState(produce={"idol_card_id":"idol-one"}))
    obj.deciders=SimpleNamespace(idol_card_id="fallback-idol")
    return obj


def test_enabled_guidance_routes_shared_session_and_identity(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","1")
    monkeypatch.setenv("HIRO_MECHANISM_CUSTOMIZE","1")
    obj=strategy();seen=[]
    def run(s,d,identity,**kw):
        seen.append((s,d,identity,callable(kw["leave"])))
        return True
    monkeypatch.setattr(guidance_session,"run",run)
    assert obj._special_guidance(None,entered=True) is True
    assert seen==[(obj.s,obj.deciders,"idol-one",True)]


def test_unknown_guidance_stops_without_legacy_fallback(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE","1")
    monkeypatch.setenv("HIRO_MECHANISM_CUSTOMIZE","1")
    obj=strategy()
    def run(*a,**kw):raise ValueError("incomplete scan")
    def stop(page,reason):raise RuntimeError(page+":"+reason)
    monkeypatch.setattr(guidance_session,"run",run)
    obj._stop=stop
    with pytest.raises(RuntimeError,match="SPECIAL_GUIDANCE:incomplete scan"):
        obj._special_guidance(None,entered=True)
