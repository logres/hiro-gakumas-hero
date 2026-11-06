import pytest
from hiro.loop import rescue
from hiro.loop.controller import HiroController
from hiro.run_hif import configure_run_llm


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch):
    monkeypatch.setattr(rescue, "LLM_UNKNOWN", rescue.LLM_UNKNOWN)
    monkeypatch.setattr(HiroController, "_rescuer", HiroController._rescuer)
    monkeypatch.setenv("HIRO_LLM", "claude:sonnet")


def test_cli_model_reaches_lazy_rescue_adapter(monkeypatch):
    from hiro.brain import llm
    monkeypatch.setenv("HIRO_LLM", "claude:sonnet")
    monkeypatch.delenv("HIRO_RESCUE_LLM_SPEC", raising=False)
    configure_run_llm("codex:gpt-6.1-sol")
    seen = []
    marker = object()
    def factory(spec=None, **kw):
        import os
        seen.append(spec or os.environ.get("HIRO_LLM"))
        return marker
    monkeypatch.setattr(llm, "from_spec", factory)
    r = rescue.Rescuer()
    assert r.llm is marker
    assert seen == ["codex:gpt-6.1-sol"]


def test_no_llm_disables_rescue_and_explicit_rescue_override_survives(monkeypatch):
    monkeypatch.setenv("HIRO_RESCUE_LLM_SPEC", "openai:test-model")
    monkeypatch.setenv("HIRO_RESCUE_LLM", "1")
    configure_run_llm("codex", no_llm=True)
    assert rescue.LLM_UNKNOWN is False
    import os
    assert os.environ["HIRO_RESCUE_LLM_SPEC"] == "openai:test-model"
