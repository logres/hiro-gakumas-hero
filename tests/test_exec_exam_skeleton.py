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
    monkeypatch.setattr(ex, "_stale_before_tap", lambda f: None)
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
