"""Hosted request preflight, commit, and last-mile transport preparation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

from core.providers.agentic_protocol import EphemeralCredential

from core.runtime.hosted_agentic_models import HostedAgenticLoopError


@dataclass(frozen=True)
class HostedTransportAuthorization:
    """One freshly resolved authority and credential at an egress boundary."""

    context: object
    credential: EphemeralCredential | None


class HostedTransportAuthorityGuard:
    """Re-resolve every live authority input immediately before provider I/O."""

    def __init__(
        self,
        *,
        context,
        prepared_request,
        request_builder,
        authority_refresher,
        credential_resolver,
        credential_required: bool,
    ) -> None:
        self.context = context
        self.prepared_request = prepared_request
        self.request_builder = request_builder
        self.authority_refresher = authority_refresher
        self.credential_resolver = credential_resolver
        self.credential_required = credential_required

    def authorize(self) -> HostedTransportAuthorization:
        """Fail closed if authority, request policy, or credentials changed."""
        authority = self.authority_refresher(self.context)
        effective_context = replace(
            self.context,
            effective_authority=authority,
        )
        self.request_builder.revalidate_for_transport(
            self.prepared_request,
            context=effective_context,
        )
        credential = self.credential_resolver(effective_context)
        if self.credential_required and credential is None:
            raise HostedAgenticLoopError(
                "provider_credential_authorization_missing"
            )
        return HostedTransportAuthorization(
            context=effective_context,
            credential=credential,
        )


async def preflight_and_commit_hosted_request(
    *,
    request_builder,
    prepared_request,
    request_preflight,
    credential,
    require_preflight: bool,
    transport_guard: HostedTransportAuthorityGuard,
):
    """Run provider preflight before full live authorization and egress CAS."""
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
    authorized_context = transport_guard.authorize().context
    return replace(
        request_builder.commit(prepared_request, context=authorized_context),
        endpoint_capability_snapshot_digest=endpoint_snapshot_digest,
    )


__all__ = [
    "HostedTransportAuthorization",
    "HostedTransportAuthorityGuard",
    "preflight_and_commit_hosted_request",
]
