"""Code-owned remote agentic data-policy identities."""

from __future__ import annotations


REMOTE_PREVIEW_EGRESS_POLICY_ID = "remote-agentic-contained"
REMOTE_PREVIEW_EGRESS_POLICY_REVISION = "2"
REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID = "remote-agentic-full-workspace"
REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION = "1"


def remote_data_policy_requires_fake_data_attestation(
    policy_id: str,
    revision: str,
) -> bool:
    """Return whether one policy identity still uses the fake-data gate."""
    return not (
        str(policy_id) == REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID
        and str(revision) == REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION
    )


def remote_profile_requires_fake_data_attestation(profile: object | None) -> bool:
    """Return whether a remote profile still uses the contained fake-data gate."""
    return remote_data_policy_requires_fake_data_attestation(
        str(getattr(profile, "egress_policy_id", "")),
        str(getattr(profile, "egress_policy_revision", "")),
    )


__all__ = [
    "REMOTE_FULL_WORKSPACE_EGRESS_POLICY_ID",
    "REMOTE_FULL_WORKSPACE_EGRESS_POLICY_REVISION",
    "REMOTE_PREVIEW_EGRESS_POLICY_ID",
    "REMOTE_PREVIEW_EGRESS_POLICY_REVISION",
    "remote_data_policy_requires_fake_data_attestation",
    "remote_profile_requires_fake_data_attestation",
]
