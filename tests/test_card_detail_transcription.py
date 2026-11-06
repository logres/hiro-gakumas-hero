import json

import pytest

from hiro.brain.card_detail_transcription import transcribe_card_detail
from hiro.brain.llm import LLMResult, MockLLM

pytestmark = pytest.mark.synthetic


def args():
    return dict(image_jpeg=b"\xff\xd8mock-jpeg", identity={"slot": 2, "card_id": "generic", "upgrade": 1},
                raw_ocr_lines=["好印象7"], snapshot_sha256="a"*64, detail_sha256="b"*64)


def test_mock_transcription_is_unverified_and_freeze_compatible():
    llm = MockLLM([{"lines": ["好印象+7"], "uncertain_spans": []}])
    result = transcribe_card_detail(llm, **args())
    assert result["status"] == "model_transcription_unverified"
    assert result["lines"] == ["好印象+7"]
    assert result["provenance"]["identity"] == args()["identity"]
    assert result["provenance"]["detail_sha256"] == "b"*64
    assert len(result["provenance"]["encoded_image_sha256"]) == 64
    assert result["provenance"]["prompt_version"] == "card_detail_transcription@1.0"
    assert result["llmtrace"] is not None
    assert "game knowledge" in llm.calls[0][0]
    json.dumps(result)


def test_plain_adapter_protocol_receives_exact_image_without_retry():
    class Adapter:
        name, model = "custom-api-or-cli", "model"
        calls = 0

        def ask_json_image(self, system, user, image_jpeg):
            self.calls += 1
            assert image_jpeg == args()["image_jpeg"]
            return LLMResult({"lines": ["条件の場合、", "効果+4"], "uncertain_spans": ["icon"]}, "", .1)

    llm = Adapter()
    result = transcribe_card_detail(llm, **args())
    assert result["status"] == "model_transcription_unverified" and llm.calls == 1
    assert result["provenance"]["adapter"] == llm.name


@pytest.mark.parametrize("reply", [None, {"lines": [], "uncertain_spans": []},
    {"lines": [7], "uncertain_spans": []}, {"lines": ["x"*501], "uncertain_spans": []},
    {"lines": ["ok"], "uncertain_spans": [], "identity": {"card_id": "invented"}},
    {"lines": ["ok"], "uncertain_spans": "none"}])
def test_invalid_or_model_identity_response_is_not_promoted(reply):
    llm = MockLLM([reply])
    assert transcribe_card_detail(llm, **args())["status"] == "unavailable"
    assert len(llm.calls) == 1


def test_failure_and_unsupported_adapter_do_not_retry():
    assert transcribe_card_detail(object(), **args())["status"] == "unavailable"
    llm = MockLLM([RuntimeError("failure")])
    assert transcribe_card_detail(llm, **args())["status"] == "unavailable"
    assert len(llm.calls) == 1


def test_invalid_input_does_not_call_model():
    llm = MockLLM([])
    assert transcribe_card_detail(llm, **{**args(), "snapshot_sha256": "path"})["status"] == "unavailable"
    assert llm.calls == []
