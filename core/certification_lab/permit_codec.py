"""Bounded canonical signed-permit encoding with exact typed domain decoding."""

import base64
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.permit import (
    LabApiTarget, LabBudgetScope, LabCandidateIdentity, LabExecutionPermit,
    LabNativeTarget, LabSessionGrant, LabWorkspaceScope,
)
from core.providers.agentic_models import AgenticRuntimePolicy, RoutingConstraint
from core.providers.capability_models import RuntimeCapabilitySet

MAX_PERMIT_BYTES = 65_536


@dataclass(frozen=True)
class SignedLabExecutionPermit:
    permit: LabExecutionPermit
    signature: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(permit_bytes(self.permit)).hexdigest()


def permit_bytes(permit: LabExecutionPermit) -> bytes:
    permit.validate()
    payload = asdict(permit)
    for key in ("issued_at", "expires_at"):
        payload[key] = payload[key].isoformat()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_PERMIT_BYTES:
        raise LabAuthorizationError("lab_permit_invalid")
    return encoded


def sign_lab_permit(permit: LabExecutionPermit, *, private_key) -> SignedLabExecutionPermit:
    """Operator-only pure signing; no worker bootstrap loads this private key."""
    return SignedLabExecutionPermit(permit, base64.b64encode(private_key.sign(permit_bytes(permit))).decode())


def verify_lab_permit(signed: SignedLabExecutionPermit, *, public_key: bytes,
                      installation_id: str, now: datetime | None = None) -> LabExecutionPermit:
    try:
        content = permit_bytes(signed.permit)
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            base64.b64decode(signed.signature, validate=True), content,
        )
    except (InvalidSignature, ValueError, TypeError) as error:
        raise LabAuthorizationError("lab_permit_signature_invalid") from error
    permit = signed.permit
    if permit.installation_id != installation_id:
        raise LabAuthorizationError("lab_installation_mismatch")
    instant = now or datetime.now(UTC)
    if not permit.issued_at <= instant < permit.expires_at:
        raise LabAuthorizationError("lab_permit_expired")
    return permit


def decode_permit(content: bytes) -> LabExecutionPermit:
    try:
        if not isinstance(content, bytes) or len(content) > MAX_PERMIT_BYTES:
            raise ValueError
        payload = json.loads(content, object_pairs_hook=_unique_keys)
        target = payload["target"]
        target_type = {"api_profile": LabApiTarget, "native_connection": LabNativeTarget}[target["scope"]]
        payload["target"] = target_type(**target)
        payload["candidate"] = LabCandidateIdentity(**payload["candidate"])
        scope = payload["workspace"]
        scope["sessions"] = tuple(LabSessionGrant(**value) for value in scope["sessions"])
        payload["workspace"] = LabWorkspaceScope(**scope)
        payload["budget"] = LabBudgetScope(**payload["budget"])
        payload["reasoning_efforts"] = tuple(payload["reasoning_efforts"])
        caps = payload["capability_ceiling"]
        caps["attachment_modalities"] = tuple(caps["attachment_modalities"])
        payload["capability_ceiling"] = RuntimeCapabilitySet(**caps)
        policy = payload["policy_ceiling"]
        for field in ("allowed_surface_kinds", "allowed_tool_handles", "allowed_remote_data_classes"):
            policy[field] = tuple(policy[field])
        payload["policy_ceiling"] = AgenticRuntimePolicy(**policy)
        route = payload["routing_constraint"]
        for field in ("allowed_upstream_ids", "allowed_quantizations"):
            route[field] = tuple(route[field])
        payload["routing_constraint"] = RoutingConstraint(**route)
        for field in ("issued_at", "expires_at"):
            payload[field] = datetime.fromisoformat(payload[field])
        permit = LabExecutionPermit(**payload)
        # Require the complete current schema and canonical representation. No
        # omitted default domain, ambiguous duplicate keys or alternate payload.
        if permit_bytes(permit) != content:
            raise ValueError
        return permit
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise LabAuthorizationError("lab_permit_invalid") from error


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result
