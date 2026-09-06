"""Publisher-owned trust and independent, exact-run review before publication.

Workers supply artifacts, never a trust map. The operator installs the public
trust policy in the publisher account; private signing keys are not stored here.
"""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import stat

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.providers.certification_artifacts import canonical_artifact, verify_retained_run
from core.providers.certification_live_receipt import decode_certification_json
from core.providers.certification_pipeline import verify_certification_run
from core.providers.certification_records import signed_run_from_json, signed_run_to_json
from core.providers.errors import CapabilityCertificateError


@dataclass(frozen=True)
class CertificationReview:
    signer_key_id: str
    signed_run_digest: str
    artifacts_digest: str
    reviewed_at: str
    signature: str


def review_payload(*, signed_run_digest, artifacts_digest, reviewed_at) -> bytes:
    return canonical_artifact({
        "schema": "maverick-certification-independent-review.v1",
        "decision": "approved", "signed_run_digest": signed_run_digest,
        "artifacts_digest": artifacts_digest, "reviewed_at": reviewed_at,
    })


def signed_artifact_digest(signed) -> str:
    return hashlib.sha256(signed_run_to_json(signed).encode()).hexdigest()


def artifact_manifest_digest(refs) -> str:
    return hashlib.sha256(canonical_artifact(sorted(refs))).hexdigest()


class CertificationPublicationAuthority:
    """A separate publisher dependency; it reloads policy on every publication."""

    def __init__(self, *, trust_policy_path: Path, evidence_store):
        self.trust_policy_path = Path(trust_policy_path)
        self.evidence_store = evidence_store

    def verify(self, signed, review: CertificationReview, *, cwd: Path):
        # Nested observation dictionaries are mutable even in a frozen record.
        # Detach them from the submitter before verifying any signature or bytes.
        signed = signed_run_from_json(signed_run_to_json(signed))
        policy = _read_policy(self.trust_policy_path)
        worker = _principal(policy, "collectors", signed.signer_key_id)
        reviewer = _principal(policy, "reviewers", review.signer_key_id)
        if worker[0] == reviewer[0] or worker[1] == reviewer[1]:
            raise CapabilityCertificateError("certification_review_not_independent")
        run = verify_certification_run(
            signed, trusted_keys={signed.signer_key_id: Ed25519PublicKey.from_public_bytes(worker[1])},
            cwd=cwd,
        )
        if run.behavioral_evidence["reviewer_ref"] != reviewer[0]:
            raise CapabilityCertificateError("certification_reviewer_mismatch")
        refs = verify_retained_run(run, self.evidence_store)
        if (review.signed_run_digest != signed_artifact_digest(signed)
                or review.artifacts_digest != artifact_manifest_digest(refs)):
            raise CapabilityCertificateError("certification_review_target_mismatch")
        try:
            reviewed_at = datetime.fromisoformat(review.reviewed_at)
            now = datetime.now(UTC)
            if (reviewed_at.tzinfo is None or not run.certification_completed_at <= reviewed_at <= now
                    or now - reviewed_at > timedelta(days=1)):
                raise ValueError
            Ed25519PublicKey.from_public_bytes(reviewer[1]).verify(
                base64.b64decode(review.signature, validate=True),
                review_payload(signed_run_digest=review.signed_run_digest,
                               artifacts_digest=review.artifacts_digest, reviewed_at=review.reviewed_at),
            )
        except (ValueError, TypeError, InvalidSignature) as error:
            raise CapabilityCertificateError("certification_review_invalid") from error
        # Retain both signatures as part of the certificate's evidence closure.
        signed_ref = self.evidence_store.put(signed_run_to_json(signed).encode())
        review_ref = self.evidence_store.put(canonical_artifact(review.__dict__))
        return run, tuple(sorted({*refs, signed_ref, review_ref}))


def _principal(policy, role, key_id):
    try:
        principal = policy[role][key_id]
        identity = principal["principal_ref"]
        key = base64.b64decode(principal["public_key"], validate=True)
        if (set(principal) != {"principal_ref", "public_key"} or len(key) != 32
                or not isinstance(identity, str) or len(identity) != 64
                or any(c not in "0123456789abcdef" for c in identity)):
            raise ValueError
        return identity, key
    except (KeyError, ValueError, TypeError) as error:
        raise CapabilityCertificateError("certification_signer_untrusted") from error


def _read_policy(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                    or metadata.st_mode & 0o022):
                raise ValueError
            policy = decode_certification_json(source.read(65_537), max_bytes=65_536)
        if (set(policy) != {"schema", "collectors", "reviewers"}
                or policy["schema"] != "maverick-certification-publisher-trust.v1"
                or not isinstance(policy["collectors"], dict) or not policy["collectors"]
                or not isinstance(policy["reviewers"], dict) or not policy["reviewers"]):
            raise ValueError
        # Aliases for the same principal/key must not manufacture independence.
        workers = [_principal(policy, "collectors", k) for k in policy["collectors"]]
        reviewers = [_principal(policy, "reviewers", k) for k in policy["reviewers"]]
        if any(w[0] == r[0] or w[1] == r[1] for w in workers for r in reviewers):
            raise CapabilityCertificateError("certification_review_not_independent")
        return policy
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise CapabilityCertificateError("certification_publisher_policy_invalid") from error
