"""ExamAdvisor / ExamStateSource 默认实现：不需要模拟器、KAA、识别层也能跑（合成局面）。"""

import pytest

from hiro import plugins
from hiro.brain.cards import CardView, DrinkView
from hiro.brain.state import CAMPUS_HIRO, BattleState, ExamMemory
from hiro.contracts import Action, Preview
from hiro.defaults.advisor import RuleLLMAdvisor, preview_rows
from hiro.defaults.exam_state import ScreenExamStateSource, screen_state


def _card(slot, name, cid, available=True):
    return CardView(slot, name, cid, 0, available, "active", 3, 0, None, "パラメータ+10")


def _state(hand, drinks=(), remaining=8):
    mem = ExamMemory(exam="r1")
    st = BattleState.build(mem, CAMPUS_HIRO, source="screen", remaining_turns=remaining, hp=20, genki=10, motivation=5,
                           impression=0, score=1000, buffs={}, attr="Da", multiplier_permil=None, npc_scores=None,
                           my_rank_index=None, deck_count=None, pitem_charges=None, statuses=None, attr_permil=None,
                           hand=list(hand), drinks=list(drinks))
    return st, mem


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.delenv("HIRO_LLM", raising=False)
    plugins._cache.clear()


def test_plugins_resolve_defaults():
    adv = plugins.get("exam_advisor")
    src = plugins.get("exam_state_source")
    assert isinstance(adv, RuleLLMAdvisor) and isinstance(src, ScreenExamStateSource)
    assert isinstance(adv, plugins.ExamAdvisor) and isinstance(src, plugins.ExamStateSource)


def test_advisor_without_llm_picks_legal_action():
    st, mem = _state([_card(0, "テスト", "c-1"), _card(1, "テスト2", "c-2")])
    legal = [Action.from_legal(a) for a in st.legal_actions()]
    d = RuleLLMAdvisor(CAMPUS_HIRO).decide(st, mem, None, legal)
    assert d.action.legal_key() in {a.legal_key() for a in legal}


@pytest.mark.parametrize("context", [{"idol": "i_card-kllj-3-000"}, {"idol": None}, {}, None])
def test_advisor_round_unknown_identity_clears_previous_profile(monkeypatch, context):
    from hiro.brain.llm import MockLLM, load_prompt

    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    llm = MockLLM([])
    advisor = RuleLLMAdvisor(CAMPUS_HIRO, llm)
    advisor.on_round_start(2, context)
    assert advisor.round_no == 2
    assert advisor.profile is advisor.brain.profile is None
    assert advisor.brain.llm is llm
    assert advisor.brain.system == load_prompt("exam_generic.md")
    assert advisor.brain.new_memory("r2").item_charges_left is None
    assert llm.calls == []


def test_advisor_round_different_known_identity_replaces_profile(monkeypatch):
    from dataclasses import replace
    from hiro.brain.llm import MockLLM

    # A second registered profile exercises the lifecycle without introducing
    # a role-specific playbook or depending on future master-data additions.
    other = replace(CAMPUS_HIRO, idol_id="synthetic-other", item_charges=2)
    # test_brain_imports removes/reimports state during the full suite. Patch
    # the registry used by this advisor's actual resolver, not a newer module.
    resolver = RuleLLMAdvisor.on_round_start.__globals__["profile_for"]
    monkeypatch.setitem(resolver.__globals__["IDOLS"], other.idol_id, other)
    llm = MockLLM([])
    advisor = RuleLLMAdvisor(CAMPUS_HIRO, llm)
    previous = advisor.brain
    advisor.on_round_start(2, {"idol": other.idol_id})
    assert advisor.profile is advisor.brain.profile is other
    assert advisor.brain is not previous and advisor.brain.llm is llm
    assert advisor.brain.new_memory("r2").item_charges_left == 2
    assert llm.calls == []


def test_advisor_round_equivalent_skin_identity_keeps_brain():
    from hiro.brain.llm import MockLLM

    llm = MockLLM([])
    advisor = RuleLLMAdvisor(CAMPUS_HIRO, llm)
    previous = advisor.brain
    advisor.on_round_start(2, {"idol": CAMPUS_HIRO.idol_id.replace("i_card-", "i_card-skin-")})
    assert advisor.profile is CAMPUS_HIRO
    assert advisor.brain is previous and advisor.brain.llm is llm
    assert llm.calls == []


def test_advisor_with_previews_follows_best_expected():
    st, mem = _state([_card(0, "A", "c-a"), _card(1, "B", "c-b")])
    legal = [Action.from_legal(a) for a in st.legal_actions()]
    previews = [Preview(action=Action.from_legal("play:0"), expected=1000.0, vs_best_se=0.0),
                Preview(action=Action.from_legal("play:1"), expected=5000.0, vs_best_se=0.0),
                Preview(action=Action.from_legal("skip"), expected=10.0, vs_best_se=0.0)]
    rows = preview_rows(previews, legal)
    assert rows[0]["legal_action"] == "play:1"
    d = RuleLLMAdvisor(CAMPUS_HIRO).decide(st, mem, previews, legal)
    assert d.action.legal_key() == "play:1"


class _Frame:
    def __init__(self, raw):
        self.raw, self.img, self.cards, self.drinks = raw, None, [], []
        self.remaining, self.hp, self.genki, self.hand = 7, 18, 5, None


def test_state_source_reads_screen_fields(monkeypatch):
    import hiro.defaults.exam_state as es

    monkeypatch.setattr(es, "screen_fields", lambda raw, session=None, img=None: {"remaining_turns": 6, "hp": 15, "score": 2000})
    src = ScreenExamStateSource()
    src.begin({"profile": CAMPUS_HIRO})
    st, why = src.read(_Frame({"hand_layout": "ok"}), ExamMemory(exam="r1"))
    assert why == "screen" and st.remaining_turns == 6 and st.hp == 15 and src.confidence() == "screen"
    assert src.previews(st) is None


def test_state_source_overlay_frame_is_skipped():
    src = ScreenExamStateSource()
    src.begin({"profile": CAMPUS_HIRO})
    st, why = src.read(_Frame({"hand_layout": "overlay"}), ExamMemory(exam="r1"))
    assert st is None and why == "hand_overlay"


def test_screen_state_fills_from_frame_when_unreadable():
    st = screen_state(ExamMemory(exam="r1"), CAMPUS_HIRO, {}, _Frame({}))
    assert st.remaining_turns == 7 and st.hp == 18 and st.genki == 5


def test_prompt_explains_missing_status_icons(monkeypatch):
    st, _ = _state([_card(0, "A", "c-a")])
    st.motivation = st.impression = None
    g = type(st).to_prompt_dict.__globals__  # 别的测试可能重新导入过模块：改实例所属模块的全局名
    monkeypatch.setitem(g, "status_icons_missing", lambda: True)
    d = st.to_prompt_dict()
    assert "effect_names_unavailable" in d and "capture_icons" in d["effect_names_unavailable"]
    monkeypatch.setitem(g, "status_icons_missing", lambda: False)
    assert "effect_names_unavailable" not in st.to_prompt_dict()


def test_out_of_legal_rechooses_by_rule_not_first(monkeypatch):
    st, mem = _state([_card(0, "A", "c-a"), _card(1, "B", "c-b")])
    adv = RuleLLMAdvisor(CAMPUS_HIRO)
    from hiro.brain.rules import Decision as BD

    monkeypatch.setattr(adv.brain, "decide", lambda s, m: BD("play:5", "越界", "llm"))
    import hiro.defaults.advisor as a

    monkeypatch.setattr(a, "guard_llm", lambda s, m, b, d: d)
    legal = [Action.from_legal(x) for x in ("play:1", "skip")]  # 只有第 1 张和结束回合合法
    d = adv.decide(st, mem, None, legal)
    assert d.action.legal_key() in {"play:1", "skip"} and any("不在合法动作里" in w for w in d.warnings)
