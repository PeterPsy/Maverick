"""Bind Google probe receipts to the catalog observed before every request."""

from dataclasses import asdict, fields, replace
import re

from core.providers.certification_target import api_profile_target_digest, builtin_api_certification_profile
from core.providers.errors import CapabilityCertificateError
from core.providers.google_interactions_catalog import GoogleInteractionsCatalogSnapshot
from core.runtime.execution_binding import canonical_digest


_FIELDS = {field.name for field in fields(GoogleInteractionsCatalogSnapshot)}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def observed_google_probe_target(snapshot: GoogleInteractionsCatalogSnapshot) -> str:
    """Use verified model/API observations, not an unchecked local target label."""
    if not isinstance(snapshot, GoogleInteractionsCatalogSnapshot):
        _fail()
    return _validate_snapshot(asdict(snapshot))


def validate_google_probe_catalog_receipt(receipt: dict) -> None:
    snapshots = receipt["catalog_snapshots"]
    if not isinstance(snapshots, list) or len(snapshots) != receipt["request_count"] or not snapshots:
        _fail()
    first_digest = None
    for snapshot in snapshots:
        if _validate_snapshot(snapshot) != receipt["target_digest"]:
            _fail()
        digest = snapshot["catalog_snapshot_digest"]
        if first_digest is not None and digest != first_digest:
            _fail()
        first_digest = digest


def _validate_snapshot(snapshot) -> str:
    if not isinstance(snapshot, dict) or set(snapshot) != _FIELDS:
        _fail()
    profile = builtin_api_certification_profile("google-ai-studio")
    if (
        snapshot["api_version"] != profile.provider_api_version
        or snapshot["operation_id"] != "CreateInteraction"
        or snapshot["model_name"] != f"models/{profile.model_id}"
        or snapshot["model_version"] != profile.model_revision
        or any(snapshot[key] is not True for key in ("streaming", "usage_accounting", "tool_calling"))
    ):
        _fail()
    for key, minimum in (
        ("input_token_limit", profile.context_policy.max_request_input_tokens),
        ("output_token_limit", profile.policy_ceiling.max_output_tokens),
    ):
        if type(snapshot[key]) is not int or not minimum <= snapshot[key] <= 100_000_000:
            _fail()
    for key in ("endpoint_schema_digest", "model_record_digest", "catalog_snapshot_digest"):
        if not isinstance(snapshot[key], str) or not _DIGEST.fullmatch(snapshot[key]):
            _fail()
    projection = {key: value for key, value in snapshot.items() if key != "catalog_snapshot_digest"}
    if canonical_digest(projection) != snapshot["catalog_snapshot_digest"]:
        _fail()
    return api_profile_target_digest(replace(
        profile, model_id=snapshot["model_name"].removeprefix("models/"),
        model_revision=snapshot["model_version"], provider_api_version=snapshot["api_version"],
    ))


def _fail():
    raise CapabilityCertificateError("certification_google_catalog_receipt_invalid")
