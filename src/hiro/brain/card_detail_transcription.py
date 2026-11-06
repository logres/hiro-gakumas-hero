"""One image-adapter call for literal, explicitly unverified detail transcription."""
import hashlib
import json
import re
from dataclasses import asdict

from hiro.brain.llm import load_prompt, prompt_version
from hiro.contracts import llm_trace_from_call

PROMPT = "card_detail_transcription.md"


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _lines(value, *, empty):
    return (isinstance(value, list) and (empty or bool(value)) and len(value) <= 40
            and all(isinstance(v, str) and bool(v.strip()) and len(v) <= 500 for v in value)
            and sum(map(len, value)) <= 6000)


def transcribe_card_detail(llm, *, image_jpeg, identity, raw_ocr_lines,
                           snapshot_sha256, detail_sha256):
    """Return a JSON-compatible record without changing card semantics or identity.

    The caller provides an already verified selected detail crop. Identity and
    snapshot hashes remain caller evidence; this function never trusts identity
    returned by the model, opens files, controls devices, or retries a call.
    """
    unavailable = {"status": "unavailable", "lines": [], "uncertain_spans": [],
                   "provenance": None, "llmtrace": None}
    keys = ("slot", "card_id", "upgrade")
    if (not isinstance(identity, dict) or type(identity.get("slot")) is not int
            or identity["slot"] < 0 or not isinstance(identity.get("card_id"), str)
            or not identity["card_id"].strip() or len(identity["card_id"]) > 200
            or type(identity.get("upgrade")) is not int or identity["upgrade"] < 0
            or not _hash(snapshot_sha256) or not _hash(detail_sha256)
            or not isinstance(image_jpeg, bytes) or not image_jpeg.startswith(b"\xff\xd8")
            or len(image_jpeg) > 10_000_000 or not _lines(raw_ocr_lines, empty=True)):
        return {**unavailable, "reason": "invalid_input"}
    if not callable(getattr(llm, "ask_json_image", None)):
        return {**unavailable, "reason": "image_adapter_unavailable"}
    trusted_identity = {k: identity[k] for k in keys}
    version = prompt_version(PROMPT)
    provenance = {"identity": trusted_identity, "snapshot_sha256": snapshot_sha256,
                  "detail_sha256": detail_sha256,
                  "encoded_image_sha256": hashlib.sha256(image_jpeg).hexdigest(),
                  "adapter": getattr(llm, "name", "unknown"),
                  "model": getattr(llm, "model", None), "prompt_version": version}
    unavailable = {**unavailable, "provenance": provenance}
    try:
        user = json.dumps({"raw_ocr_lines": raw_ocr_lines}, ensure_ascii=False)
        response = llm.ask_json_image(load_prompt(PROMPT), user, image_jpeg)
        trace = asdict(llm_trace_from_call(response.record(prompt_version=version)))
        unavailable = {**unavailable, "llmtrace": trace}
        if response.error:
            return {**unavailable, "reason": "model_error"}
        data = response.data
        if (not isinstance(data, dict) or set(data) != {"lines", "uncertain_spans"}
                or not _lines(data.get("lines"), empty=False)
                or not _lines(data.get("uncertain_spans"), empty=True)):
            return {**unavailable, "reason": "invalid_response"}
        return {**unavailable, "status": "model_transcription_unverified",
                "lines": list(data["lines"]), "uncertain_spans": list(data["uncertain_spans"])}
    except Exception:
        return {**unavailable, "reason": "adapter_failure"}
