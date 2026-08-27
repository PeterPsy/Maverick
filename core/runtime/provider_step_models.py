"""Revisioned WAL records for one hosted provider request/response step."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.runtime.provider_state import (
    ProviderPrivateEnvelope,
    provider_private_envelope_from_document,
)


ProviderRequestStatus = Literal["ready", "journaled"]
ProviderAcceptanceStatus = Literal["pending", "accepted"]
ProviderStreamStatus = Literal["pending", "completed", "failed"]
ProviderStepStatus = Literal["pending", "staged"]
ProviderCollectionStatus = Literal["pending", "complete", "not_applicable"]
ProviderPairingStatus = Literal[
    "pending",
    "ready",
    "consumed",
    "not_applicable",
]
ProviderCommitStatus = Literal[
    "pending",
    "committed",
    "rolled_back",
    "recovery_required",
]


@dataclass(frozen=True)
class ProviderStepJournalRecord:
    """One idempotent saga whose mutable fields advance only through CAS."""

    journal_id: str
    schema_version: str
    workspace_id: str
    session_id: str
    turn_id: str
    request_id: str
    step_index: int
    runtime_engine_id: str
    adapter_id: str
    adapter_version: str
    model_provider_id: str
    provider_protocol: str
    provider_api_version: str | None
    codec_id: str
    codec_version: str
    codec_schema_version: str
    codec_content_type: str
    base_provider_state_revision: int
    base_provider_state_digest: str | None
    pairing_source_journal_id: str | None
    request_status: ProviderRequestStatus
    acceptance_status: ProviderAcceptanceStatus
    stream_status: ProviderStreamStatus
    step_status: ProviderStepStatus
    proposal_status: ProviderCollectionStatus
    disposition_status: ProviderCollectionStatus
    result_status: ProviderCollectionStatus
    pairing_status: ProviderPairingStatus
    commit_status: ProviderCommitStatus
    provider_response_id: str | None
    provider_upstream_id: str | None
    staged_provider_state: ProviderPrivateEnvelope | None
    proposal_ids: tuple[str, ...]
    disposition_ids: tuple[str, ...]
    result_ids: tuple[str, ...]
    observed_call_count: int
    final_output_validated: bool
    stream_failure_reason_code: str | None
    recovery_reason_code: str | None
    recovery_detail_private_ref: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    request_journaled_at: datetime | None = None
    accepted_at: datetime | None = None
    staged_at: datetime | None = None
    stream_completed_at: datetime | None = None
    stream_failed_at: datetime | None = None
    proposals_completed_at: datetime | None = None
    dispositions_completed_at: datetime | None = None
    results_completed_at: datetime | None = None
    pairing_ready_at: datetime | None = None
    committed_at: datetime | None = None
    rolled_back_at: datetime | None = None
    recovery_required_at: datetime | None = None


def provider_step_journal_from_document(
    document: Mapping[str, object],
) -> ProviderStepJournalRecord:
    """Hydrate tuple/envelope fields while rejecting malformed persisted state."""
    payload = dict(document)
    for field_name in ("proposal_ids", "disposition_ids", "result_ids"):
        payload[field_name] = tuple(payload.get(field_name, ()))
    envelope = payload.get("staged_provider_state")
    if isinstance(envelope, Mapping):
        payload["staged_provider_state"] = provider_private_envelope_from_document(
            envelope
        )
    elif envelope is not None and not isinstance(envelope, ProviderPrivateEnvelope):
        raise ValueError("Staged provider state must be an envelope object.")
    payload.setdefault("schema_version", "1")
    payload.setdefault("provider_api_version", None)
    payload.setdefault("base_provider_state_digest", None)
    payload.setdefault("pairing_source_journal_id", None)
    payload.setdefault("provider_response_id", None)
    payload.setdefault("provider_upstream_id", None)
    payload.setdefault("recovery_reason_code", None)
    payload.setdefault("recovery_detail_private_ref", None)
    payload.setdefault("stream_failure_reason_code", None)
    for field_name in (
        "request_journaled_at",
        "accepted_at",
        "staged_at",
        "stream_completed_at",
        "stream_failed_at",
        "proposals_completed_at",
        "dispositions_completed_at",
        "results_completed_at",
        "pairing_ready_at",
        "committed_at",
        "rolled_back_at",
        "recovery_required_at",
    ):
        payload.setdefault(field_name, None)
    return ProviderStepJournalRecord(**payload)
