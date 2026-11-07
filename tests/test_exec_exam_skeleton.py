"""考试执行器骨架（hiro.exec.exam.run_exam）：局面走 ExamStateSource 插件、出招走 ExamAdvisor 插件；
执行原语（等稳、弹窗、点击、等变化）用替身，只验证调用顺序与失败分支。"""

from types import SimpleNamespace as NS

import pytest

pytest.importorskip("kaa")  # 执行器调 KAA 的定位 / 资源
pytest.importorskip("hiro.brain.battle")  # 记忆管理在策略层（brain）
pytest.importorskip("hiro.perception.lesson")  # HUD 数字读法在识别层

import hiro.exec.exam as ex  # noqa: E402
from hiro.brain.rules import Decision  # noqa: E402
from hiro.contracts import Action, Decision as DC  # noqa: E402


class Rec:
    def __init__(self):
        self.events = []

    def log(self, kind, **kw):
        self.events.append(kind)


class Memory:
    def __init__(self):
        self.turn, self.last_remaining, self.history, self.plan, self.blocked = 1, None, [], [], []

    def block(self, a):
        self.blocked.append(a)


class Brain:
    profile = NS(idol_id="i_test")

    def __init__(self):
        self.commits = []

    def new_memory(self, exam):
        return Memory()

    def commit(self, state, memory, d):
        self.commits.append(d.action)


class State:
    drinks, hand = [], []

    def legal_actions(self):
        return ["play:0", "skip"]


class Source:
    def __init__(self, reads):
        self.reads, self.calls = list(reads), []

    def begin(self, ctx):
        self.calls.append("begin")
        self.context = ctx

    def read(self, frame, memory):
        self.calls.append("read")
        return self.reads.pop(0) if self.reads else (State(), None)

    def confidence(self):
        return "screen"

    def executed(self, action, result):
        self.calls.append(("executed", action.kind.value, result.ok))

    def previews(self, state):
        return None

    def end(self, result):
        self.calls.append("end")


class Advisor:
    def __init__(self):
        self.calls = []

    def on_round_start(self, n, ctx):
        self.calls.append(("start", n))

    def decide(self, state, memory, previews, legal):
        self.calls.append(("decide", [a.kind.value for a in legal]))
        return DC(Action.play_card(0), "测试", "rule")

    def on_round_end(self, result):
        self.calls.append("end")


@pytest.fixture
def env(monkeypatch):
    t = [0.0]
    loops = {"n": 0}

    class FakeLoop:
        def __init__(self, interval):
            pass

        def __iter__(self):
            return self

        def __next__(self):
            loops["n"] += 1
            if loops["n"] > 50:
                raise StopIteration
            return None

    frame = NS(img="img", t=0.0, remaining=5, hp=20, genki=10, cards=[], drinks=[], signature=("sig",))
    monkeypatch.setattr(ex, "Loop", FakeLoop)
    monkeypatch.setattr(ex, "device", NS(screenshot=lambda: "img", click=lambda *a: None))
    monkeypatch.setattr(ex, "_handle_dialogs", lambda img, slow=False: False)
    monkeypatch.setattr(ex, "_settle_fast", lambda img, **kw: frame)
    monkeypatch.setattr(ex, "_stable_frame", lambda **kw: frame)
    monkeypatch.setattr(ex, "_stale_before_tap", lambda f, **kw: None)
    monkeypatch.setattr(ex, "_execute", lambda d, f: [[100, 1010]])
    monkeypatch.setattr(ex, "_wait_change", lambda sig: True)
    monkeypatch.setattr(ex, "_play_missed", lambda f, c: False)
    monkeypatch.setattr(ex.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(ex, "sleep", lambda s: t.__setitem__(0, t[0] + s))
    return t


def test_one_step_calls_plugins_in_order(env):
    src, adv, brain = Source([]), Advisor(), Brain()
    done = iter([False, True])
    ex.run_exam(brain, "r1", Rec(), lambda: next(done), source=src, advisor=adv)
    assert src.calls == ["begin", "read", ("executed", "PlayCard", True), "end"]
    assert adv.calls == [("start", 1), ("decide", ["PlayCard", "Skip"]), "end"] and brain.commits == ["play:0"]


def test_state_none_waits_then_rereads(env):
    """局面来源给不出（例如过场白光 hand_overlay）：不决策，换帧重读。"""
    src, adv = Source([(None, "hand_overlay"), (None, "hand_overlay")]), Advisor()
    done = iter([False, False, False, True])
    ex.run_exam(Brain(), "r1", Rec(), lambda: next(done), source=src, advisor=adv)
    assert src.calls.count("read") == 3 and [c for c in adv.calls if c[0] == "decide"] == [("decide", ["PlayCard", "Skip"])]


def test_missing_plugins_raise(monkeypatch, env):
    monkeypatch.setattr(ex, "_plugin", lambda kind: None)
    with pytest.raises(RuntimeError):
        ex.run_exam(Brain(), "r1", Rec(), lambda: True)


def test_explicit_identity_reaches_source_without_profile_substitution(env):
    src, adv = Source([]), Advisor()
    ex.run_exam(Brain(), "qualify-1", Rec(), lambda: True, source=src, advisor=adv,
                idol_card_id="i_card-skin-kllj-3-000")
    assert src.context["idol_card_id"] == "i_card-skin-kllj-3-000"
    other = Source([])
    ex.run_exam(Brain(), "qualify-1", Rec(), lambda: True, source=other, advisor=adv)
    assert other.context["idol_card_id"] is None


def test_detail_preopen_change_reobserves_without_deciding(env, monkeypatch):
    readings = iter([False, True])
    monkeypatch.setattr(ex, "_review_current_card_details", lambda *args, **kwargs: next(readings))
    src, adv, brain = Source([]), Advisor(), Brain()
    done = iter([False, False, True])
    ex.run_exam(brain, "r1", Rec(), lambda: next(done), source=src, advisor=adv)
    assert src.calls.count("read") == 2
    assert brain.commits == ["play:0"]
    assert sum(c[0] == "start" for c in adv.calls if isinstance(c, tuple)) == 1


@pytest.mark.parametrize("completed", [False, True])
def test_only_observed_exam_end_finishes_saved_memory(env, monkeypatch, tmp_path, completed):
    saved = []
    monkeypatch.setattr(ex, "load_exam_memory", lambda *args: None)
    monkeypatch.setattr(ex, "save_exam_memory", lambda *args, **kw: saved.append(kw))
    session = NS(state=NS(exam_session=NS(label=None)), trace=NS(dir=tmp_path))
    def ended():
        if not completed:
            raise RuntimeError("interrupted before exam result")
        return True
    if completed:
        ex.run_exam(Brain(), "qualify-3", Rec(), ended, source=Source([]), advisor=Advisor(), session=session)
    else:
        with pytest.raises(RuntimeError, match="interrupted"):
            ex.run_exam(Brain(), "qualify-3", Rec(), ended, source=Source([]), advisor=Advisor(), session=session)
    assert saved[-1]["finished"] is completed


@pytest.mark.parametrize("rejections", [1, 4])
def test_stale_decision_keeps_frozen_input_without_execution_or_memory_commit(env, monkeypatch, tmp_path, rejections):
    monkeypatch.setenv("HIRO_PLAN_EFFECT_REVALIDATION", "1")
    records, recoveries = [], []
    frozen = {"schema_version": "1.0", "sha256": "frozen-test-input", "input": {"turn": 1}}
    monkeypatch.setattr(ex, "load_exam_memory", lambda *a: None)
    monkeypatch.setattr(ex, "save_exam_memory", lambda *a, **kw: None)
    monkeypatch.setattr(ex, "freeze_exam_decision_input", lambda *a, **kw: frozen)
    monkeypatch.setattr(ex, "_stale_before_tap", lambda frame, **kw: "fresh hand unreadable")
    monkeypatch.setattr(ex, "_move_to_redo", lambda *a: None)
    monkeypatch.setattr(ex, "_execute", lambda *a: pytest.fail("stale action must not execute"))
    session = NS(state=NS(exam_session=NS(label=None), produce={}), trace=NS(dir=tmp_path),
                 last="decision-observation", note=lambda *a: None,
                 recover=lambda *a: recoveries.append(a),
                 record=lambda obs, **kw: records.append((obs, kw)))
    source, advisor, brain = Source([]), Advisor(), Brain()
    original_decide = advisor.decide
    def proposing_plan(state, memory, previews, legal):
        # BattleBrain stores followups before the executor validates the frame.
        memory.plan = [{"action": "play", "card": "requires-rejected-action"}]
        return original_decide(state, memory, previews, legal)
    advisor.decide = proposing_plan
    done = iter([False] * rejections + [True])
    memory = ex.run_exam(brain, "qualify-3", Rec(), lambda: next(done),
                         source=source, advisor=advisor, session=session)
    assert len(records) == rejections and len(recoveries) == rejections
    obs, payload = records[0]
    assert obs == "decision-observation" and payload["exam_decision_input"] is frozen
    assert payload["decision"].action == Action.play_card(0)
    assert payload.get("execution") is None and brain.commits == []
    assert memory.plan == []  # Followups cannot survive their unexecuted prerequisite.
    assert not any(isinstance(c, tuple) and c[0] == "executed" for c in source.calls)


@pytest.mark.parametrize("fresh_sig, expected", [
    (None, "点击前读不到"),
    (((6, 29, 30), ((1, 2),)), "剩余回合"),
    (((7, 29, 30), ((3, 4),)), "手牌位置"),
    (((7, None, 30), ((1, 2),)), None),
])
def test_stale_diagnostic_reuses_single_fresh_frame(monkeypatch, fresh_sig, expected):
    old, fresh = object(), object()
    original = ((7, 29, 30), ((1, 2),))
    screenshots, signatures, records = [], [], []
    def shoot():
        screenshots.append(fresh)
        return fresh
    def signature(image):
        signatures.append(image)
        return original if image is old else fresh_sig
    monkeypatch.setattr(ex, "device", NS(screenshot=shoot))
    monkeypatch.setattr(ex, "_lite_sig", signature)
    result = ex._stale_before_tap(NS(img=old), on_rejected=lambda image, data: records.append((image, data)))
    assert screenshots == [fresh]
    assert signatures == [old, fresh]
    if expected is None:
        assert result is None and records == []
    else:
        assert result.startswith(expected)
        assert records == [(fresh, {"reason": result, "decision_signature": original,
                                   "fresh_signature": fresh_sig, "image_role": "rejected_fresh_frame"})]


def test_stale_diagnostic_failure_preserves_rejection(monkeypatch):
    old, fresh = object(), object()
    monkeypatch.setattr(ex, "device", NS(screenshot=lambda: fresh))
    monkeypatch.setattr(ex, "_lite_sig", lambda image: ((7, 29, 30), ((1, 2),)) if image is old else None)
    def fail(image, data):
        raise RuntimeError("recorder unavailable")
    assert ex._stale_before_tap(NS(img=old), on_rejected=fail).startswith("点击前读不到")


@pytest.mark.parametrize("baseline, raises", [(None, False), (None, True)])
def test_stale_diagnostic_keeps_unreadable_baseline_behavior(monkeypatch, baseline, raises):
    def signature(image):
        if raises:
            raise RuntimeError("unreadable")
        return baseline
    monkeypatch.setattr(ex, "_lite_sig", signature)
    monkeypatch.setattr(ex, "device", NS(screenshot=lambda: pytest.fail("unexpected screenshot")))
    assert ex._stale_before_tap(NS(img=object()), on_rejected=lambda *args: pytest.fail("unexpected record")) is None
