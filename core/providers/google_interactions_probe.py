"""Opt-in Google round trips with live catalog preflight before every transport."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
import tempfile
from uuid import uuid4

from core.providers.agentic_filesystem_probe import AgenticFilesystemListProbe
from core.providers.agentic_protocol import EphemeralCredential
from core.providers.agentic_probe_validation import validate_probe_response
from core.providers.errors import CapabilityCertificateError
from core.providers.google_interactions_catalog import preflight_google_interactions_catalog
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.providers.google_interactions_probe_catalog import observed_google_probe_target
from core.providers.google_interactions_probe_contract import (
    CERTIFICATION_PROBE_TOOL_ROUNDS, CERTIFIED_REASONING_EFFORTS, PROBE_TOOL_NAME,
    GoogleInteractionsProbeResult, google_probe_request, google_probe_result,
)


async def probe_google_interactions(
    *,
    credential: EphemeralCredential,
    client: GoogleInteractionsAgenticClient | None = None,
    reasoning_efforts: tuple[str, ...] = CERTIFIED_REASONING_EFFORTS,
    request_interval_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> GoogleInteractionsProbeResult:
    """Run two tool continuations and finalization only on the verified live tuple."""
    test_run_id = f"google-interactions-live:{uuid4()}"
    efforts = tuple(str(value).strip().lower() for value in reasoning_efforts)
    events = []
    snapshots = []
    request_count = 0
    filesystem_result_count = 0

    def result(reason):
        return google_probe_result(
            test_run_id, events, reason, request_count, efforts,
            filesystem_result_count, tuple(snapshots),
        )

    if efforts != CERTIFIED_REASONING_EFFORTS:
        return result("probe_reasoning_effort_invalid")
    if client is None:
        from core.providers.certification_probe_budget import CertificationProbeTransport
        from core.providers.google_interactions_transport import GoogleInteractionsHttpTransport

        client = GoogleInteractionsAgenticClient(state_mode="stateless", transport=CertificationProbeTransport(
            GoogleInteractionsHttpTransport(), provider_id="google-ai-studio",
        ))
    with tempfile.TemporaryDirectory(prefix="maverick-google-agentic-probe-") as temp_dir:
        filesystem_probe = AgenticFilesystemListProbe.create(Path(temp_dir))
        for effort in efforts:
            private = None
            tool_results = []
            for ordinal in range(1, CERTIFICATION_PROBE_TOOL_ROUNDS + 2):
                final = ordinal == CERTIFICATION_PROBE_TOOL_ROUNDS + 1
                request = google_probe_request(
                    f"{test_run_id}:{effort}:{ordinal}", reasoning_effort=effort,
                    tool_definition=filesystem_probe.definition, private_state=private,
                    tool_results=tuple(tool_results), finalize=final,
                )
                if request_count and request_interval_seconds > 0:
                    await sleep(request_interval_seconds)
                try:
                    snapshot = await asyncio.to_thread(
                        preflight_google_interactions_catalog, request, credential=credential,
                    )
                    observed_google_probe_target(snapshot)
                except (GoogleInteractionsProtocolError, CapabilityCertificateError) as error:
                    return result(error.reason_code)
                if snapshots and snapshot.catalog_snapshot_digest != snapshots[0].catalog_snapshot_digest:
                    return result("probe_catalog_drift")
                snapshots.append(snapshot)
                response = [event async for event in client.create_response(request, credential=credential)]
                request_count += 1
                events.extend(response)
                error = next((event.error_code for event in response if event.event_type == "error"), None)
                if error or not validate_probe_response(response, final=final):
                    return result(error or ("probe_final_response_missing" if final else "probe_tool_call_missing"))
                if final:
                    continue
                call = next(event.tool_call for event in response if event.event_type == "tool_call")
                private = next(event.provider_private_state for event in response if event.event_type == "provider_state")
                if call.provider_tool_name != PROBE_TOOL_NAME:
                    return result("probe_tool_call_missing")
                try:
                    tool_results.append(filesystem_probe.execute(call))
                except (OSError, TypeError, ValueError, RuntimeError):
                    return result("probe_filesystem_list_failed")
                filesystem_result_count += 1
    return result("ok")
