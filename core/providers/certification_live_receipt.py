"""Bounded live protocol receipts; a green subprocess alone is not evidence."""

import json
import math
import re

from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


_COMMON = {"target_digest", "run_nonce", "succeeded", "request_count", "reasoning_efforts"}
_GOOGLE_FLAGS = {"saw_streaming", "saw_tool_call", "saw_filesystem_list", "saw_usage", "saw_private_state"}
_GOOGLE = _COMMON | _GOOGLE_FLAGS | {"reason_code", "test_run_id", "result_summary_digest"}
_OPENROUTER = _COMMON | {
    "catalog_snapshot_digest", "catalog_model_record_digest", "catalog_zdr_record_digest",
    "context_length", "filesystem_result_count", "max_completion_tokens",
    "supports_tool_choice_none", "upstream_id",
}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def decode_certification_json(raw: str | bytes, *, max_bytes=262_144):
    """Reject duplicate keys, non-finite numbers, oversized and malformed input."""
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(encoded) > max_bytes:
            raise ValueError
        return json.loads(encoded, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant, parse_float=_finite_float)
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise CapabilityCertificateError("certification_json_invalid") from error


def validate_live_probe_receipt(
    receipt, *, provider_id: str, target_digest: str, run_nonce: str,
):
    """Return only reviewed counter/digest metadata from the exact probe run."""
    from core.providers.certification_target import builtin_api_reasoning_efforts

    expected_fields = {"google-ai-studio": _GOOGLE, "openrouter": _OPENROUTER}.get(provider_id)
    if not isinstance(receipt, dict) or expected_fields is None or set(receipt) != expected_fields:
        _fail()
    efforts = builtin_api_reasoning_efforts(provider_id)
    if (receipt["target_digest"] != target_digest or receipt["run_nonce"] != run_nonce
            or not re.fullmatch(r"[0-9a-f]{32}", run_nonce)
            or receipt["succeeded"] is not True
            or receipt["reasoning_efforts"] != list(efforts)):
        _fail()
    rounds = 2 if provider_id == "google-ai-studio" else 3
    if type(receipt["request_count"]) is not int or receipt["request_count"] != (rounds + 1) * len(efforts):
        _fail()
    if provider_id == "google-ai-studio":
        if (receipt["reason_code"] != "ok" or any(receipt[key] is not True for key in _GOOGLE_FLAGS)
                or not isinstance(receipt["test_run_id"], str)
                or not re.fullmatch(r"google-interactions-live:[0-9a-f-]{36}", receipt["test_run_id"])):
            _fail()
        summary = {key: receipt[key] for key in (*_GOOGLE_FLAGS, "reason_code", "request_count", "reasoning_efforts")}
        if receipt["result_summary_digest"] != canonical_digest(summary):
            _fail()
    else:
        if (receipt["supports_tool_choice_none"] is not True or receipt["upstream_id"] != "deepinfra/fp8"
                or type(receipt["filesystem_result_count"]) is not int
                or receipt["filesystem_result_count"] != rounds * len(efforts)):
            _fail()
        for key in ("context_length", "max_completion_tokens"):
            if type(receipt[key]) is not int or not 16_384 <= receipt[key] <= 100_000_000:
                _fail()
        for key in ("catalog_snapshot_digest", "catalog_model_record_digest", "catalog_zdr_record_digest"):
            if not isinstance(receipt[key], str) or not _DIGEST.fullmatch(receipt[key]):
                _fail()
    return receipt


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError
    return parsed


def _fail():
    raise CapabilityCertificateError("certification_live_receipt_invalid")
