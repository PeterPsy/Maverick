"""Hosted request preflight, commit, and last-mile transport preparation."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from core.runtime.hosted_agentic_models import HostedAgenticLoopError


async def preflight_and_commit_hosted_request(
    *,
    request_builder,
    prepared_request,
    context,
    request_preflight,
    credential,
    require_preflight: bool,
):
    """Run the provider preflight before authority revalidation and egress CAS."""
    request = prepared_request.request
    endpoint_snapshot_digest = ""
    if request_preflight is not None:
        try:
            endpoint_snapshot = await asyncio.to_thread(
                request_preflight,
                request,
                credential,
            )
        except Exception as error:
            raise HostedAgenticLoopError(
                str(
                    getattr(
                        error,
                        "reason_code",
                        "provider_endpoint_preflight_failed",
                    )
                )
            ) from error
        endpoint_snapshot_digest = str(
            getattr(endpoint_snapshot, "snapshot_digest", "") or ""
        )
        if (
            len(endpoint_snapshot_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in endpoint_snapshot_digest
            )
        ):
            raise HostedAgenticLoopError(
                "provider_endpoint_preflight_invalid"
            )
    elif require_preflight:
        raise HostedAgenticLoopError(
            "provider_endpoint_preflight_unavailable"
        )
    return replace(
        request_builder.commit(
            prepared_request,
            context=context,
        ),
        endpoint_capability_snapshot_digest=endpoint_snapshot_digest,
    )


__all__ = ["preflight_and_commit_hosted_request"]
