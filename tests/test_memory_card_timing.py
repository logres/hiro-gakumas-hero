"""回忆技能卡只在确认入手后计为已有；全部使用合成编成与 trace。"""

import pytest

from hiro import kaa_env
from hiro.brain import formation_plan
from hiro.loop.ledger import owned_cards


def _plan(chosen):
    return {"idol": {"idol_card_id": "idol-test"}, "support": {},
            "memory": {"cards": [row["card_id"] for row in chosen], "chosen": chosen}}


def test_formation_timing_seeds_only_confirmed_start(monkeypatch):
    plan = _plan([{"card_id": "early", "timing": "start"}, {"card_id": "after-exam", "timing": "mid"},
                  {"card_id": "unread", "timing": None}])
    monkeypatch.setattr(formation_plan, "load", lambda path: plan)
    monkeypatch.setattr(kaa_env, "MEMORY_CARDS", ())
    monkeypatch.setattr(kaa_env, "MEMORY_CARD_TIMINGS", ())
    monkeypatch.setattr(kaa_env, "_MEMORY_CARD_TIMINGS_CONFIG", ())
    monkeypatch.delenv("HIRO_FORMATION_PLAN", raising=False)

    kaa_env.apply_formation_plan("idol-test", "synthetic-plan.json")
    assert kaa_env.MEMORY_CARD_TIMINGS == ("start", "mid", "unknown")
    assert kaa_env.start_memory_cards() == ("early",)
    assert set(owned_cards([], kaa_env.start_memory_cards())) == {"early"}

    observed_deck = {"observation": {"page": {"name": "DECK_LIST"},
                                     "fields": {"complete": True, "deck": [{"card_id": "early"},
                                                                           {"card_id": "after-exam"}]}},
                     "state": {}, "decision": None, "execution": None}
    assert set(owned_cards([observed_deck], kaa_env.start_memory_cards())) == {"early", "after-exam"}


def test_legacy_plan_and_manual_timing_are_conservative(monkeypatch):
    plan = _plan([{"card_id": "legacy"}])
    monkeypatch.setattr(formation_plan, "load", lambda path: plan)
    monkeypatch.setattr(kaa_env, "MEMORY_CARDS", ())
    monkeypatch.setattr(kaa_env, "MEMORY_CARD_TIMINGS", ())
    monkeypatch.setattr(kaa_env, "_MEMORY_CARD_TIMINGS_CONFIG", ())
    monkeypatch.delenv("HIRO_FORMATION_PLAN", raising=False)
    kaa_env.apply_formation_plan("idol-test", "old-plan.json")
    assert kaa_env.start_memory_cards() == ()
    assert kaa_env._checked_memory_timings(("a", "b"), ()) == ("unknown", "unknown")
    assert kaa_env._checked_memory_timings(("a", "b"), ("start", "mid")) == ("start", "mid")
    with pytest.raises(ValueError, match="逐项对应"):
        kaa_env._checked_memory_timings(("a", "b"), ("start",))
