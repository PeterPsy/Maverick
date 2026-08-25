"""Append-only checks for immutable Codex profile artifact revisions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


MANIFEST_PATH = Path("core/providers/codex_profile_artifacts.json")


def verify_codex_profile_artifact_history(repository_root: Path) -> str | None:
    """Reject edits to any artifact digest already present in Git history."""
    current = _manifest_from_bytes((repository_root / MANIFEST_PATH).read_bytes())
    baseline_refs = _baseline_refs(repository_root)
    if not baseline_refs:
        return None
    for baseline_ref in baseline_refs:
        baseline_payload = subprocess.run(
            ["git", "show", f"{baseline_ref}:{MANIFEST_PATH.as_posix()}"],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
        if baseline_payload.returncode == 0:
            baseline = _manifest_from_bytes(baseline_payload.stdout)
            compare_codex_profile_artifact_manifests(baseline, current)
    return baseline_refs[0]


def compare_codex_profile_artifact_manifests(
    baseline: dict[str, object],
    current: dict[str, object],
) -> None:
    """Require all published revision-to-digest assignments to remain immutable."""
    baseline_revisions = _revisions(baseline)
    current_revisions = _revisions(current)
    changed = [
        revision
        for revision, digest in baseline_revisions.items()
        if current_revisions.get(revision) != digest
    ]
    if changed:
        raise RuntimeError(
            "codex_profile_artifact_history_changed:" + ",".join(sorted(changed))
        )
    baseline_current = str(baseline.get("current_revision") or "").strip()
    current_revision = str(current.get("current_revision") or "").strip()
    if _numeric_revision(current_revision) < _numeric_revision(baseline_current):
        raise RuntimeError("codex_profile_revision_regressed")


def _baseline_refs(repository_root: Path) -> list[str]:
    history = subprocess.run(
        ["git", "log", "--format=%H", "--", MANIFEST_PATH.as_posix()],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line.strip() for line in history.splitlines() if line.strip()]


def _manifest_from_bytes(payload: bytes) -> dict[str, object]:
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("codex_profile_artifact_manifest_invalid")
    revisions = _revisions(document)
    current_revision = str(document.get("current_revision") or "").strip()
    if (
        document.get("schema_version") != "1"
        or document.get("adapter_id") != "codex-app-server"
        or current_revision not in revisions
    ):
        raise RuntimeError("codex_profile_artifact_manifest_invalid")
    return document


def _revisions(document: dict[str, object]) -> dict[str, str]:
    raw = document.get("revisions")
    if not isinstance(raw, dict):
        raise RuntimeError("codex_profile_artifact_manifest_invalid")
    revisions = {str(key): str(value) for key, value in raw.items()}
    if any(
        not revision.isdigit()
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for revision, digest in revisions.items()
    ):
        raise RuntimeError("codex_profile_artifact_manifest_invalid")
    return revisions


def _numeric_revision(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return -1
