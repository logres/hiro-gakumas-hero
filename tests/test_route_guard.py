"""Non-やる気 page guards must not invoke the legacy card/drink rankings."""

from types import SimpleNamespace

from hiro.brain import route_guard
from hiro.contracts.action import ActionKind
from hiro.contracts.game_state import GameState


IDOL = "i_card-kllj-3-001"


class FakeCatalog:
    def one(self, table, key):
        assert table == "IdolCard" and key == IDOL
        return {"examEffectType": "ProduceExamEffectType_ExamReview",
                "planType": "ProducePlanType_Plan2"}

    def card(self, key, upgrade=0):
        if key == "trouble" or upgrade not in (0, 1):
            raise KeyError(key)
        return {"category": "ProduceCardCategory_MentalSkill",
                "effectGroupIds": ["effect_group-visible-exam_review-000"] if key == "review" else []}


def _decider(yaruki=False):
    d = SimpleNamespace(idol_card_id=IDOL, profile=None, overflow_skip=False)
    d._uses_yaruki_policy = lambda state: yaruki
    return d


def _state(**fields):
    return GameState(produce={"idol_card_id": IDOL}, page_fields=fields)


def test_legacy_path_is_untouched():
    assert route_guard.guard(_decider(True), "SKILL_CARD_REMOVAL", _state()) is None


def test_destructive_and_unadapted_pages_are_guarded():
    cases = {
        "SKILL_CARD_REMOVAL": (ActionKind.REMOVE_CARD, {"cancel": True}),
        "SKILL_CARD_CHANGE_1": (ActionKind.WAIT, None),
        "SKILL_CARD_CHANGE_2": (ActionKind.CHANGE_CARD, {"cancel": True}),
        "CONSULT": (ActionKind.SHOP_END, {}),
        "SPECIAL_GUIDANCE": (ActionKind.CUSTOMIZE_END, {}),
        "HIF_ROUND_INTERVAL": (ActionKind.INTERVAL_END, {}),
    }
    for page, (kind, args) in cases.items():
        decision = route_guard.guard(_decider(), page, _state())
        assert decision.action.kind is kind
        if args is not None:
            assert decision.action.args == args
        assert "route_policy_skip" in decision.warnings
        assert "非やる気路线" in decision.reason


def test_study_uses_current_idol_effect_and_avoids_change(monkeypatch):
    monkeypatch.setattr(route_guard, "catalog", FakeCatalog)
    choices = [{"index": 0, "text": "好印象 +3", "trouble": False, "cost_hp": 0},
               {"index": 1, "text": "セレクトチェンジ", "trouble": False, "cost_hp": 0},
               {"index": 2, "text": "眠気", "trouble": True, "cost_hp": 0}]
    state = _state(choices=choices)
    state.produce.update(mode="produce-007", step=3, stamina=12)
    decision = route_guard.guard(_decider(), "STUDY", state)
    assert decision.action.kind is ActionKind.EVENT_SELECT
    assert decision.action.args == {"select": 0}
    choices[0]["text"] = "セレクトチェンジ"
    assert route_guard.guard(_decider(), "STUDY", state).action.kind is ActionKind.WAIT


def test_study_unknown_choices_waits(monkeypatch):
    monkeypatch.setattr(route_guard, "catalog", FakeCatalog)
    assert route_guard.guard(_decider(), "STUDY", _state()).action.kind is ActionKind.WAIT


def test_study_change_day_does_not_pick_plain_even_without_change_text(monkeypatch):
    monkeypatch.setattr(route_guard, "catalog", FakeCatalog)
    choices = [{"index": 0, "text": "好印象", "trouble": False, "cost_hp": 0},
               {"index": 1, "text": "やる気", "trouble": False, "cost_hp": 0},
               {"index": 2, "text": "眠気", "trouble": True, "cost_hp": 0}]
    state = _state(choices=choices)
    state.produce.update(mode="produce-007", step=10, stamina=12)
    decision = route_guard.guard(_decider(), "STUDY", state)
    assert decision.action.kind is ActionKind.EVENT_SELECT
    assert decision.action.args == {"select": 2}
    choices[2]["text"] = ""
    assert route_guard.guard(_decider(), "STUDY", state).action.kind is ActionKind.WAIT


def test_study_never_selects_unaffordable_or_unverified_hp(monkeypatch):
    monkeypatch.setattr(route_guard, "catalog", FakeCatalog)
    choices = [{"index": 0, "text": "好印象", "trouble": False, "cost_hp": 5},
               {"index": 1, "text": "やる気", "trouble": False, "cost_hp": 0}]
    state = _state(choices=choices)
    state.produce.update(mode="produce-007", step=3)
    assert route_guard.guard(_decider(), "STUDY", state).action.kind is ActionKind.EVENT_SELECT
    assert route_guard.guard(_decider(), "STUDY", state).action.args == {"select": 1}
    choices[1]["text"] = "セレクトチェンジ"
    assert route_guard.guard(_decider(), "STUDY", state).action.kind is ActionKind.WAIT
    state.produce["stamina"] = 4
    assert route_guard.guard(_decider(), "STUDY", state).action.kind is ActionKind.WAIT


def test_enhance_only_known_recommended_upgrade(monkeypatch):
    monkeypatch.setattr(route_guard, "catalog", FakeCatalog)
    cards = [{"index": 0, "card_id": "other", "upgrade": 0},
             {"index": 1, "card_id": "review", "upgrade": 0}]
    decision = route_guard.guard(_decider(), "SKILL_CARD_ENHANCE", _state(cards=cards))
    assert decision.action.kind is ActionKind.ENHANCE_CARD
    assert decision.action.args == {"card_id": "review", "index": 1, "upgrade": 0}
    assert route_guard.guard(_decider(), "SKILL_CARD_ENHANCE", _state(cards=cards[:1])).action.args == {"cancel": True}
    assert route_guard.guard(_decider(), "SKILL_CARD_ENHANCE", _state(cards=cards[:1], cancelable=False)).action.kind is ActionKind.WAIT


def test_drink_skips_without_old_ranking_and_preserves_overflow():
    decider = _decider()
    assert route_guard.guard(decider, "SELECT_DRINK", _state(), can_skip=True).action.kind is ActionKind.EXCLUDE_CARD
    assert route_guard.guard(decider, "SELECT_DRINK", _state(), can_skip=False).action.kind is ActionKind.WAIT
    decision = route_guard.guard(decider, "PDRINK_MAX", _state())
    assert decision.action.kind is ActionKind.DISCARD_DRINK
    assert decision.action.args == {"discard": [], "receive": False}
    assert decider.overflow_skip is True
