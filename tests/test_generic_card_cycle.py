"""Closed cycle oracles and real prompt/guard wiring; not model quality."""
import copy
import json
import pytest
from hiro.brain.llm import LLMResult
from hiro.contracts import Action
from tools import replay_exam_choice as replay
from tools.check_synthetic_card_cycle import CASES, cycle_oracle, freeze
from tools import check_synthetic_card_cycle as check
pytestmark = pytest.mark.synthetic


@pytest.mark.parametrize("case", CASES["cycle_cases"], ids=lambda c: c["id"])
def test_closed_cycle_membership_does_not_assume_random_distribution(case):
    assert cycle_oracle(case) == case["target_next"]




@pytest.mark.parametrize("case", CASES["cycle_cases"] + CASES["choice_cases"], ids=lambda c: c["id"])
@pytest.mark.parametrize("swapped", [False, True])
def test_public_cases_survive_real_generic_prompt_and_guard(case, swapped):
    payload, expected, assumptions = freeze(case, swapped=swapped)
    seen = []
    class Mock:
        name = "mock"
        model = "offline-wiring-only"
        def ask_json(self, system, user):
            seen.append((system, json.loads(user[user.index("{"):])))
            answer = {"action": expected, "reason": "封闭合成管线检查", "plan": []}
            return LLMResult(answer, json.dumps(answer, ensure_ascii=False), 0,
                             adapter=self.name, model=self.model)
    with replay._flags(payload["flags"]):
        result = replay._decide(copy.deepcopy(payload), Mock())
    assert len(seen) == 1
    system, user = seen[0]
    assert "version: 1.12" in system
    assert "通常回合开始抽3张" in system
    assert "除外牌不参与普通重洗" in system
    assert "未知机会不当作0，也不当作必然" in system
    assert user["public_info"] == "人工封闭前提：" + json.dumps(assumptions, ensure_ascii=False)
    assert payload["profile"] is None and payload["idol_card_id"] is None
    assert Action.from_dict(result["action"]).legal_key() == expected
    assert result["source"] == "llm"


def test_one_shot_choices_are_opposite_under_closed_horizon():
    wait, final = CASES["choice_cases"]
    assert wait["future_score"] > wait["current_score"] > 0
    assert final["current_score"] > final["future_score"] == 0
    assert wait["expected"] == "skip" and final["expected"] == "play:0"


def test_runner_offline_hashes_and_no_quality_claim(monkeypatch):
    monkeypatch.setattr(check, "from_spec", lambda _: pytest.fail("offline must not create an adapter"))
    report = check.run()
    assert report["model_calls_used"] == 0 and len(report["cases"]) == 4
    assert not report["sources_changed_during_run"]
    for case in report["cases"]:
        assert case["input_sha256"] == check.generic._hash(case["input"])
        assert case["model_quality_status"] == "not_measured"
        assert case["direct_model_checks"] is None
        assert "expected_action" not in json.dumps(case["input"])


def test_runner_mock_records_first_reply_without_quality_claim(monkeypatch):
    class Mock:
        name = "mock"
        model = "wiring-only"
        def ask_json(self, *args):
            reply = {"action": "skip", "reason": "mock", "plan": []}
            return LLMResult(reply, json.dumps(reply), 0, adapter=self.name, model=self.model)
    monkeypatch.setattr(check, "from_spec", lambda _: Mock())
    report = check.run(adapter="codex", max_model_calls=1)
    assert report["model_calls_used"] == 1
    case = report["cases"][0]
    assert case["model_quality_status"] == "mock_adapter_not_quality"
    assert case["first_model_choice"]["decision"] is not None
    assert case["first_model_checks"] is None and case["direct_model_checks"] is None


@pytest.mark.parametrize("kwargs", [{"adapter": "codex"}, {"max_model_calls": -1}, {"adapter": "other", "max_model_calls": 1}])
def test_runner_rejects_invalid_caps_or_adapter(kwargs):
    with pytest.raises(ValueError):
        check.run(**kwargs)
