"""Route applicability uses master enum, never the idol name or main attribute."""

import sqlite3
from types import SimpleNamespace

import pytest

from hiro.brain import route_policy as policy
from hiro.state.catalog import Catalog, CatalogUnavailable


@pytest.fixture
def master(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE IdolCard (id TEXT, examEffectType TEXT)")
    db.executemany("INSERT INTO IdolCard VALUES (?, ?)", [
        ("i_card-shro-3-007", "ProduceExamEffectType_ExamCardPlayAggressive"),
        ("i_card-kllj-3-000", "ProduceExamEffectType_ExamReview"),
        ("unknown", "ProduceExamEffectType_Unknown"),
        ("missing", None), ("malformed", "ExamCardPlayAggressive"),
    ])
    monkeypatch.setattr(policy, "catalog", lambda: Catalog(db))
    yield
    db.close()


def test_confirmed_enum_and_skin_normalization(master, monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    assert policy.recommended_effect("i_card-kllj-3-000") == "ExamReview"
    assert not policy.legacy_or_yaruki("i_card-kllj-3-000")
    assert policy.legacy_or_yaruki("i_card-shro-3-007")
    assert policy.yaruki_route("i_card-skin-shro-3-007")


@pytest.mark.parametrize("identity", [None, "", "absent", "unknown", "missing", "malformed"])
def test_unknown_never_becomes_yaruki(master, monkeypatch, identity):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    assert policy.recommended_effect(identity) is None
    assert not policy.legacy_or_yaruki(identity)


@pytest.mark.parametrize("error", [CatalogUnavailable("no db"), sqlite3.OperationalError("bad schema")])
def test_unavailable_master_excludes_specialist_policy(monkeypatch, error):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    def fail():
        raise error
    monkeypatch.setattr(policy, "catalog", fail)
    assert not policy.legacy_or_yaruki("i_card-kllj-3-000")


def test_legacy_mode_does_not_require_master(monkeypatch):
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    monkeypatch.setattr(policy, "catalog", lambda: pytest.fail("legacy mode must not read master"))
    assert policy.legacy_or_yaruki(None)
    assert policy.legacy_or_yaruki("i_card-kllj-3-000")


def test_consult_explicit_route_end_is_not_overridden(master, monkeypatch):
    from hiro.contracts import Action, ActionKind, Decision, GameState
    hif = pytest.importorskip("hiro.produce.hif")
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    strategy = hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    strategy.s = SimpleNamespace(state=GameState(
        produce={"idol_card_id": "i_card-kllj-3-000", "produce_point": 500},
        page_fields={"services": {"upgrade": {"price": 100}, "delete": {"price": 50}}}))
    decision = Decision(Action(ActionKind.SHOP_END), "当前路线跳过专用消费", "rule", .8,
                        warnings=["牌组未识别", policy.ROUTE_POLICY_SKIP])
    assert strategy._consult_open_dialog(decision, set()) is decision


def test_repeated_cancel_stops_before_forced_route_mismatch(master, monkeypatch):
    from hiro.contracts import Action, ActionKind, Decision, GameState
    hif = pytest.importorskip("hiro.produce.hif")
    from hiro.brain import deciders

    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    decision = Decision(Action(ActionKind.CHANGE_CARD, {"cancel": True}), "不适用换卡策略", "rule", .8)
    strategy = hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    state = GameState(produce={"idol_card_id": "i_card-kllj-3-000"},
                      page_fields={"cards": [{"index": 0, "card_id": "impression-core"}]})
    strategy.s = SimpleNamespace(state=state, observe=lambda **kw: None)
    strategy.deciders = SimpleNamespace(decide=lambda *a, **kw: decision)
    strategy._change_cancels = 1
    strategy._scan_change_deck = lambda: False
    monkeypatch.setattr(deciders, "choose_card_to_change", lambda *a: pytest.fail("must not force specialist cull"))
    def stop(*a, **kw):
        raise hif.UnhandledPage("route mismatch")
    strategy._stop = stop
    context = SimpleNamespace(stage=2, commit_stage2=lambda *a, **kw: pytest.fail("must not commit card change"))
    with pytest.raises(hif.UnhandledPage, match="route mismatch"):
        strategy.on_skill_card_change(context)
