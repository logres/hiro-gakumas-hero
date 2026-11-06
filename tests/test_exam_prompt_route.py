"""Explicit unprofiled idols use the neutral prompt; legacy/profile routing stays intact."""

import pytest

from hiro.brain.battle import BattleBrain
from hiro.brain.llm import MockLLM, load_prompt, prompt_version
from hiro.brain.state import CAMPUS_HIRO


def test_explicit_unknown_profile_uses_generic_prompt(monkeypatch):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", "1")
    llm = MockLLM([])
    brain = BattleBrain(None, llm)
    assert brain.system == load_prompt("exam_generic.md")
    assert brain.prompt_version == prompt_version("exam_generic.md")
    assert brain.llm is llm and llm.calls == []


@pytest.mark.parametrize("flag", [None, "0"])
def test_default_unknown_profile_preserves_old_prompt(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("HIRO_EXPLICIT_IDOL_STATE", raising=False)
    else:
        monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", flag)
    brain = BattleBrain(None, MockLLM([]))
    assert brain.system == load_prompt("exam.md")
    assert brain.prompt_version == prompt_version("exam.md")


@pytest.mark.parametrize("flag", ["0", "1"])
def test_known_profile_keeps_base_and_personal_prompt(monkeypatch, flag):
    monkeypatch.setenv("HIRO_EXPLICIT_IDOL_STATE", flag)
    brain = BattleBrain(CAMPUS_HIRO, MockLLM([]))
    names = ("exam.md", f"idols/{CAMPUS_HIRO.playbook}.md")
    assert brain.system == load_prompt(*names)
    assert brain.prompt_version == prompt_version(*names)
