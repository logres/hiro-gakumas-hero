from types import SimpleNamespace as NS

import pytest
from kaa.config.const import HifScenario
from kaa.tasks.produce.new.consts import Scene, SceneType
from hiro.produce import hif
from hiro.loop.controller import HiroController
from hiro.loop.errors import ResumeBlocked
from hiro.vision import hif as vision


def strategy(monkeypatch, result=None, *, retry=False, active=True, scenario=HifScenario.QUALIFY):
    st = hif.HiroHifStrategy.__new__(hif.HiroHifStrategy)
    st.scenario, st.exam_count = scenario, 99
    st.s = NS(state=NS(exam_session=NS(label=None)))
    calls = []
    monkeypatch.setattr(hif.HiroHifStrategy, "exams_done", 77)
    monkeypatch.setattr(vision, "is_hif_result", lambda _: active)
    monkeypatch.setattr(vision, "read_hif_result", lambda _: result or {"exam_no": 3, "passed": False})
    st._retry_if_failed = lambda label: calls.append(("retry", label)) or retry
    st._finish_exam = lambda label: calls.append(("finish", label))
    return st, calls


@pytest.mark.parametrize("number", [1, 2, 3])
@pytest.mark.parametrize("passed", [True, False])
def test_result_uses_observed_exam_number_and_existing_finish(monkeypatch, number, passed):
    st, calls = strategy(monkeypatch, {"exam_no": number, "passed": passed})
    assert st.resume_qualify_result(object()) is True
    assert st.exam_count == hif.HiroHifStrategy.exams_done == number
    label = f"qualify-{number}"
    assert st.s.state.exam_session.label == label
    assert calls == [("retry", label), ("finish", label)]


def test_retry_does_not_finish_or_enter_battle(monkeypatch):
    st, calls = strategy(monkeypatch, retry=True)
    assert st.resume_qualify_result(object()) is True
    assert calls == [("retry", "qualify-3")]


@pytest.mark.parametrize("result", [
    {"exam_no": None, "passed": False}, {"exam_no": 4, "passed": False},
    {"exam_no": True, "passed": False}, {"exam_no": 3, "passed": None},
    {"exam_no": 3, "passed": 0}])
def test_unknown_result_stops_before_any_action(monkeypatch, result):
    st, calls = strategy(monkeypatch, result)
    with pytest.raises(ResumeBlocked):
        st.resume_qualify_result(object())
    assert calls == [] and st.exam_count == 99
    assert st.s.state.exam_session.label is None


@pytest.mark.parametrize("scenario,active", [(HifScenario.MAIN, True), (HifScenario.QUALIFY, False)])
def test_other_scenario_or_page_has_no_action(monkeypatch, scenario, active):
    st, calls = strategy(monkeypatch, scenario=scenario, active=active)
    assert st.resume_qualify_result(object()) is False
    assert not calls and st.exam_count == 99


def test_controller_result_hook_requires_opt_in(monkeypatch):
    controller = HiroController.__new__(HiroController)
    calls = []
    controller.strategy = NS(resume_qualify_result=lambda img: calls.append(img) or True)
    monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    image = object()
    assert controller._before_quick_page(image) is False and not calls
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    assert controller._before_quick_page(image) is True and calls == [image]


def test_result_retry_rearms_battle_exactly_once(monkeypatch):
    st, calls = strategy(monkeypatch)
    def retry(label):
        calls.append(("retry", label))
        st.exam_restarted = True
        st.exam_count -= 1
        hif.HiroHifStrategy.exams_done = st.exam_count
        return True
    st._retry_if_failed = retry
    entered = []
    st.on_exam_entered = lambda ctx: entered.append(ctx)
    controller = HiroController.__new__(HiroController)
    controller.strategy, controller.page = st, None
    controller._last_scene = Scene(SceneType.EXAM)
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    assert controller._before_quick_page(object()) is True
    assert not entered
    assert st.exam_count == 2
    scene = Scene(SceneType.EXAM)
    for _ in range(2):
        controller._rearm_exam(scene)
        controller._dispatch(scene, controller._last_scene)
        controller._last_scene = scene
    assert len(entered) == 1
    assert st.exam_restarted is False
