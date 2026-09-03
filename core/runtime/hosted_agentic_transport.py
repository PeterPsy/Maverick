"""Hosted request preflight, commit, and last-mile transport preparation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
import hmac
import secrets

from core.providers.agentic_protocol import EphemeralCredential

from core.runtime.hosted_agentic_models import HostedAgenticLoopError


_CREDENTIAL_FINGERPRINT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class HostedTransportAuthorization:
    """One freshly resolved authority and credential at an egress boundary."""

    context: object
    credential: EphemeralCredential | None


class HostedRequestPhaseRefreshRequired(HostedAgenticLoopError):
    """Signal that a prepared exploration catalog is no longer transportable."""


class HostedTransportAuthorityGuard:
    """Bind preflight and transport while separating full and cheap checks."""

    def __init__(
        self,
        *,
        context,
        prepared_request,
        request_builder,
        policy_resolver,
        budget,
        authority_refresher,
        authority_revalidator,
        credential_resolver,
        credential_required: bool,
        preflight_credential: EphemeralCredential | None,
    ) -> None:
        self.context = context
        self.prepared_request = prepared_request
        self.request_builder = request_builder
        self.policy_resolver = policy_resolver
        self.budget = budget
        self.authority_refresher = authority_refresher
        self.authority_revalidator = authority_revalidator
        self.credential_resolver = credential_resolver
        self.credential_required = credential_required
        self.preflight_credential = preflight_credential
        self._preflight_credential_fingerprint = _credential_fingerprint(
            preflight_credential
        )
        self._authorized_authority = getattr(
            context,
            "effective_authority",
            None,
        )

    def authorize_transport(self) -> HostedTransportAuthorization:
        """Run expensive certification checks at a transport-open boundary."""
        self.budget.check_time()
        authority = self.authority_refresher(self.context)
        authorization = self._authorize(authority)
        exhaustion_reason = self.budget.tool_catalog_exhaustion_reason
        if (
            self.prepared_request.request.request_phase == "exploration"
            and exhaustion_reason is not None
        ):
            raise HostedRequestPhaseRefreshRequired(exhaustion_reason)
        self._authorized_authority = authority
        return authorization

    def revalidate_transport(self) -> HostedTransportAuthorization:
        """Run only live revocation fences before a later stream advance."""
        self.budget.check_time()
        if self._authorized_authority is None:
            raise HostedAgenticLoopError("runtime_authority_unavailable")
        authority = self.authority_revalidator(
            self.context,
            self._authorized_authority,
        )
        return self._authorize(authority)

    def authorize(self) -> HostedTransportAuthorization:
        """Retain the explicit full-boundary entrypoint for direct callers."""
        return self.authorize_transport()

    def _authorize(self, authority) -> HostedTransportAuthorization:
        effective_context = replace(
            self.context,
            effective_authority=authority,
        )
        policy = self.policy_resolver(effective_context)
        self.budget.tighten(policy)
        self.request_builder.revalidate_for_transport(
            self.prepared_request,
            context=effective_context,
            policy=policy,
        )
        credential = self.credential_resolver(effective_context)
        if self.credential_required and credential is None:
            raise HostedAgenticLoopError(
                "provider_credential_authorization_missing"
            )
        if not hmac.compare_digest(
            self._preflight_credential_fingerprint,
            _credential_fingerprint(credential),
        ):
            raise HostedAgenticLoopError(
                "provider_credential_changed_after_preflight"
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
                transport_guard.preflight_credential,
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
    authorized_context = transport_guard.authorize_transport().context
    return replace(
        request_builder.commit(prepared_request, context=authorized_context),
        endpoint_capability_snapshot_digest=endpoint_snapshot_digest,
    )


def _credential_fingerprint(
    credential: EphemeralCredential | None,
) -> bytes:
    """Return a process-local, non-bearer identity for one credential value."""
    if credential is None:
        material = b"none"
    else:
        try:
            value = credential.reveal()
        except Exception as error:
            raise HostedAgenticLoopError(
                "provider_credential_authorization_invalid"
            ) from error
        if not isinstance(value, str) or not value:
            raise HostedAgenticLoopError(
                "provider_credential_authorization_invalid"
            )
        try:
            material = b"value\x00" + value.encode("utf-8")
        except UnicodeError as error:
            raise HostedAgenticLoopError(
                "provider_credential_authorization_invalid"
            ) from error
    return hmac.new(
        _CREDENTIAL_FINGERPRINT_KEY,
        material,
        hashlib.sha256,
    ).digest()


__all__ = [
    "HostedRequestPhaseRefreshRequired",
    "HostedTransportAuthorization",
    "HostedTransportAuthorityGuard",
    "preflight_and_commit_hosted_request",
]
