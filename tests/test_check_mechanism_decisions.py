import copy
import hashlib
import json

import pytest

from hiro.brain.llm import MockLLM
from hiro.contracts import Action
from tools import check_mechanism_decisions as check

pytestmark = pytest.mark.synthetic


class Master:
    def __init__(self):
        self.cards = {}
        for (cid, up), spec in check.SPECS.items():
            name, plan, category, cost, extra_type, extra_value, text, duplicate = spec
            self.cards[cid, up] = {
                "id": cid, "upgradeCount": up, "name": name, "planType": plan, "category": category,
                "stamina": cost, "forceStamina": 0, "costType": extra_type, "costValue": extra_value,
                "produceDescriptions": [{"text": text}], "noDeckDuplication": duplicate,
                "playMovePositionType": "ProduceCardMovePositionType_Grave",
            }
        self.idols = {identity: {"id": identity, "examEffectType": "ProduceExamEffectType_" + mechanism}
                      for identity, mechanism in check.IDENTITIES}

    def card(self, cid, upgrade):
        return self.cards[cid, upgrade]

    def one(self, table, identity):
        assert table == "IdolCard"
        return self.idols[identity]


def test_cases_bind_real_definitions_slots_legality_hashes_and_assumptions():
    cases = check.build_cases(Master())
    assert len(cases) == 22
    assert {c["group"] for c in cases} == {"equal_cost_upgrade", "refund_resource_positive", "refund_resource_negative"}
    for case in cases:
        frozen = case["frozen"]
        assert hashlib.sha256(check.replay._canonical(frozen["input"])).hexdigest() == frozen["sha256"]
        assert all(len(value) == 64 for value in case["master_row_sha256"].values())
        state, memory, *_ = check.replay._state(frozen["input"])
        assert state.source == "hypothetical_master_fixture" and state.actions_left == 1 and memory.plan == []
        assert all(card.badge_score is None for card in state.hand)
        assert case["oracle"]["expected_action"] in state.legal_actions()
        if case["group"] == "refund_resource_negative":
            card = next(card for card in state.hand if card.card_id == check.REFUND)
            assert not card.available and f"play:{card.slot}" not in state.legal_actions()
    pair = [c for c in cases if c["group"] == "equal_cost_upgrade" and "kllj" in c["id"]]
    assert {case["oracle"]["expected_action"] for case in pair} == {"play:0", "play:1"}


@pytest.mark.parametrize("field,value", [
    ("stamina", 4), ("forceStamina", 1), ("produceDescriptions", [{"text": "changed +999"}]),
    ("category", "ProduceCardCategory_MentalSkill"), ("produceCardStatusEnchantId", "new-trigger"),
])
def test_changed_master_refuses_old_dominance_claim(field, value):
    master = Master()
    master.cards[check.COMMON, 1][field] = value
    with pytest.raises(ValueError, match="主数据改变"):
        check.build_cases(master)


def test_changed_identity_mechanism_refuses_case():
    master = Master()
    master.idols[check.IDENTITIES[0][0]]["examEffectType"] = "changed"
    with pytest.raises(ValueError, match="机制改变"):
        check.build_cases(master)


def test_default_is_offline_and_baseline_is_not_model_quality(monkeypatch):
    monkeypatch.setattr(check, "from_spec", lambda *a: (_ for _ in ()).throw(AssertionError("must not create model")))
    report = check.run(master=Master())
    assert report["case_count"] == 22 and report["model_measured_count"] == 0
    assert report["global_model_calls_used"] == 0
    assert all(case["model_decision"] is None and case["model_checks"] is None for case in report["cases"])
    assert "tools/check_mechanism_decisions.py" in report["versions"]["sha256_by_file"]


def test_global_cap_and_mock_never_counted_as_quality(monkeypatch):
    model = MockLLM([{"action": "skip"}, {"action": "skip"}])
    monkeypatch.setattr(check, "from_spec", lambda spec: model)
    def fake_decide(payload, adapter=None):
        if adapter is not None:
            adapter.ask_json("system", "user")
        return {"action": Action.skip().to_dict(), "source": "llm" if adapter else "rule", "plan": []}
    monkeypatch.setattr(check.replay, "_decide", fake_decide)
    report = check.run(master=Master(), adapter="codex:test", max_model_calls=2)
    assert report["global_model_calls_used"] == len(model.calls) == 2
    assert report["model_measured_count"] == 0
    assert sum(case["model_decision"] is not None for case in report["cases"]) == 2
    assert all(case["model_checks"] is None for case in report["cases"])


def test_required_continuation_is_checked_separately_from_first_move():
    case = next(c for c in check.build_cases(Master()) if c["group"] == "refund_resource_positive")
    action = Action.from_legal(case["oracle"]["expected_action"]).to_dict()
    partial = check.judge({"action": action, "plan": []}, case)
    assert partial["legal"] and partial["expected_action"] and not partial["criterion_pass"]
    full = check.judge({"action": action, "plan": [{"action": "play", "card": case["oracle"]["expected_followup"]}]}, case)
    assert full["criterion_pass"]
    extra = check.judge({"action": action, "plan": [
        {"action": "play", "card": case["oracle"]["expected_followup"]},
        {"action": "play", "card": "オトメゴコロ+"}]}, case)
    assert extra["expected_action"] and not extra["required_plan"] and not extra["criterion_pass"]


def test_guarded_model_attempt_remains_visible_as_pipeline_result(monkeypatch):
    model = MockLLM([{"action": "skip", "reason": "bad model choice"}])
    model.name = "codex-cli"  # Protocol simulation only; no CLI process is launched.
    monkeypatch.setattr(check, "from_spec", lambda spec: model)
    def guarded(payload, adapter=None):
        trace = []
        if adapter is not None:
            response = adapter.ask_json("system", "user")
            trace = [{"adapter": response.adapter, "raw": response.raw}]
        return {"action": Action.skip().to_dict(), "source": "rule", "plan": [], "llm": trace}
    monkeypatch.setattr(check.replay, "_decide", guarded)
    report = check.run(master=Master(), adapter="codex:test", max_model_calls=1)
    attempted = report["cases"][0]
    assert attempted["model_quality_status"] == "model_attempted_guarded"
    assert attempted["model_checks"] is None
    assert attempted["model_assisted_pipeline_checks"]["criterion_pass"] is False
    assert "bad model choice" in attempted["model_call_evidence"][0]["raw"]
    assert report["model_measured_count"] == 0 and report["model_attempted_guarded_count"] == 1
    assert report["cases"][1]["model_quality_status"] == "not_measured"
    assert report["cases"][1]["model_assisted_pipeline_checks"] is None


def test_source_changes_do_not_replace_starting_versions(monkeypatch):
    versions = iter([{"git_head": "before", "sha256_by_file": {}},
                     {"git_head": "after", "sha256_by_file": {}}])
    monkeypatch.setattr(check.replay, "_versions", lambda: next(versions))
    report = check.run(master=Master())
    assert report["versions"]["git_head"] == "before"
    assert report["versions_end"]["git_head"] == "after"
    assert report["sources_changed_during_run"] is True


def test_cli_output_and_exact_case_filter_without_model(tmp_path, monkeypatch):
    master = Master()
    selected = check.build_cases(master)[0]["id"]
    real_run = check.run
    monkeypatch.setattr(check, "run", lambda **kwargs: real_run(master=master, **kwargs))
    output = tmp_path / "report.json"
    assert check.main(["--case", selected, "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["case_count"] == 1 and report["cases"][0]["id"] == selected
    assert report["model_measured_count"] == 0
    with pytest.raises(ValueError, match="unknown cases"):
        real_run(master=master, case_ids=["missing"])
