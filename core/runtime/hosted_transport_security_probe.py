"""Production-composed revocation probe for the hosted provider transport."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace

from core.egress.agentic_policy import (
    AgenticEgressEvaluator,
    public_remote_egress_policy,
)
from core.egress.agentic_transforms import canonical_egress_content
from core.runtime.classification_authority import (
    revalidate_hosted_content_classification,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
)
from core.runtime.hosted_agentic_request import HostedAgenticRequestBuilder
from core.runtime.hosted_agentic_transport import (
    HostedTransportAuthorityGuard,
    preflight_and_commit_hosted_request,
)
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
)
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
)
from core.runtime.semantic_envelope_models import canonical_classification
from core.runtime.tool_catalog import RuntimeToolCatalog
from core.runtime.hosted_transport_security_probe_support import (
    PROBE_PROVIDER_ID,
    PROBE_TIME,
    PROBE_WORKSPACE_ID,
    TransportProbeClient,
    TransportProbeDecisionStore,
    TransportProbeEventClient,
    build_transport_probe_budget,
    build_transport_probe_context,
    build_transport_probe_workspace_store,
    consume_transport_probe_stream,
)


def probe_hosted_transport_revocation() -> bool:
    """Exercise prepare, endpoint preflight, commit, and the actual dispatch gate."""
    store = build_transport_probe_workspace_store()
    current = {
        "record": issue_runtime_public_content_authority(
            store,
            workspace_id=PROBE_WORKSPACE_ID,
            actor_id="core-security-probe",
            expected_revision=0,
            now=PROBE_TIME,
        )
    }
    decisions = TransportProbeDecisionStore()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        context = build_transport_probe_context(root)

        def classify(_context, provenance: str, content: object):
            digest = hashlib.sha256(
                canonical_egress_content(content)
            ).hexdigest()
            if provenance == "user_input":
                return canonical_classification(
                    classification_from_runtime_public_content_authority(
                        current["record"],
                        workspace_id=PROBE_WORKSPACE_ID,
                        provenance="user_input",
                        trust_level="trusted_actor",
                        source_ref="security-probe-input",
                        source_revision=digest,
                        source_digest=digest,
                        resource_identity="security-probe-input:1",
                    )
                )
            return HostedContentClassification(
                "public",
                "trusted_actor",
                source_ref="security-probe-input",
                source_revision=digest,
                resource_identity="security-probe-input:1",
                classification_revision=1,
                content_digest=digest,
            )

        def revalidate(_context, classification):
            return revalidate_hosted_content_classification(
                store,
                workspace_id=PROBE_WORKSPACE_ID,
                classification=classification,
            )

        builder = HostedAgenticRequestBuilder(
            egress_evaluator=AgenticEgressEvaluator(
                digest_key=b"hosted-transport-security-key!!!",
                decision_store=decisions,
            ),
            classifier=classify,
            classification_revalidator=revalidate,
        )
        arguments = {
            "context": context,
            "step": 0,
            "input_text": "synthetic public transport probe",
            "catalog": RuntimeToolCatalog(()),
            "tool_results": (),
            "provider_private_state": None,
            "egress_policy": public_remote_egress_policy(
                provider_id=PROBE_PROVIDER_ID
            ),
            "destination_upstream_id": None,
            "max_output_tokens": 32,
        }

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                asyncio.run,
                _probe_transport_boundaries(
                    builder=builder,
                    arguments=arguments,
                    store=store,
                    current=current,
                    decisions=decisions,
                    context=context,
                ),
            ).result(timeout=10)


async def _probe_transport_boundaries(
    *,
    builder,
    arguments,
    store,
    current,
    decisions,
    context,
) -> bool:
    """Compose the same production preflight/commit/stream path as the loop."""
    prepared = builder.prepare(**arguments)
    budget = build_transport_probe_budget()
    transport_guard = _transport_guard(builder, prepared, context, budget)
    preflight_called = False

    def revoking_preflight(_request, _credential):
        nonlocal preflight_called
        preflight_called = True
        current["record"] = revoke_runtime_public_content_authority(
            store,
            workspace_id=PROBE_WORKSPACE_ID,
            actor_id="core-security-probe",
            expected_revision=current["record"].revision,
            reason="negative endpoint-preflight probe",
            now=PROBE_TIME,
        )
        return SimpleNamespace(snapshot_digest="d" * 64)

    try:
        await preflight_and_commit_hosted_request(
            request_builder=builder,
            prepared_request=prepared,
            request_preflight=revoking_preflight,
            require_preflight=True,
            transport_guard=transport_guard,
        )
    except HostedAgenticLoopError as error:
        commit_denied = error.reason_code == "egress_data_class_denied"
    else:
        commit_denied = False
    if not preflight_called or not commit_denied or decisions.records:
        return False

    current["record"] = issue_runtime_public_content_authority(
        store,
        workspace_id=PROBE_WORKSPACE_ID,
        actor_id="core-security-probe",
        expected_revision=current["record"].revision,
        now=PROBE_TIME,
    )
    prepared = builder.prepare(**arguments)
    budget = build_transport_probe_budget()
    transport_guard = _transport_guard(builder, prepared, context, budget)
    request = await preflight_and_commit_hosted_request(
        request_builder=builder,
        prepared_request=prepared,
        request_preflight=lambda _request, _credential: SimpleNamespace(
            snapshot_digest="e" * 64
        ),
        require_preflight=True,
        transport_guard=transport_guard,
    )
    if (
        request.endpoint_capability_snapshot_digest != "e" * 64
        or not decisions.records
    ):
        return False
    current["record"] = revoke_runtime_public_content_authority(
        store,
        workspace_id=PROBE_WORKSPACE_ID,
        actor_id="core-security-probe",
        expected_revision=current["record"].revision,
        reason="negative last-transport-boundary probe",
        now=PROBE_TIME,
    )
    client = TransportProbeClient()
    reason_code = await consume_transport_probe_stream(
        client=client,
        request=request,
        budget=budget,
        authorize_transport=transport_guard.authorize_transport,
        revalidate_transport=transport_guard.revalidate_transport,
    )
    initial_advance_blocked = bool(
        reason_code == "egress_data_class_denied"
        and client.request_count == 0
    )
    current["record"] = issue_runtime_public_content_authority(
        store,
        workspace_id=PROBE_WORKSPACE_ID,
        actor_id="core-security-probe",
        expected_revision=current["record"].revision,
        now=PROBE_TIME,
    )
    prepared = builder.prepare(**arguments)
    budget = build_transport_probe_budget()
    transport_guard = _transport_guard(builder, prepared, context, budget)
    request = await preflight_and_commit_hosted_request(
        request_builder=builder,
        prepared_request=prepared,
        request_preflight=lambda _request, _credential: SimpleNamespace(
            snapshot_digest="f" * 64
        ),
        require_preflight=True,
        transport_guard=transport_guard,
    )
    event_client = TransportProbeEventClient()
    advances = 0

    def revoke_before_second_advance():
        nonlocal advances
        advances += 1
        if advances == 1:
            current["record"] = revoke_runtime_public_content_authority(
                store,
                workspace_id=PROBE_WORKSPACE_ID,
                actor_id="core-security-probe",
                expected_revision=current["record"].revision,
                reason="negative between-event transport probe",
                now=PROBE_TIME,
            )
        return transport_guard.revalidate_transport()

    stream_reason = await consume_transport_probe_stream(
        client=event_client,
        request=request,
        budget=budget,
        authorize_transport=transport_guard.authorize_transport,
        revalidate_transport=revoke_before_second_advance,
    )
    return bool(
        initial_advance_blocked
        and stream_reason == "egress_data_class_denied"
        and advances == 1
        and event_client.request_count == 1
        and event_client.event_count == 1
    )


def _transport_guard(builder, prepared, context, budget) -> HostedTransportAuthorityGuard:
    return HostedTransportAuthorityGuard(
        context=context,
        prepared_request=prepared,
        request_builder=builder,
        policy_resolver=lambda _current: budget.policy,
        budget=budget,
        authority_refresher=lambda current: current.effective_authority,
        authority_revalidator=lambda _current, authority: authority,
        credential_resolver=lambda _current: None,
        credential_required=False,
        preflight_credential=None,
    )


__all__ = ["probe_hosted_transport_revocation"]
