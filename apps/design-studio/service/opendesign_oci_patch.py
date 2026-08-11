"""Apply the authorized compiled OpenDesign API boundary patch."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


class BoundaryPatchError(RuntimeError):
    """Fail-closed compiled boundary patch error."""


_TOKEN_DECLARATIONS = (
    b"    const apiToken = apiTokenFromEnv();\n"
    b"    const apiAuthDisabled = isApiAuthDisabled();\n"
)
_PATCHED_TOKEN_DECLARATIONS = _TOKEN_DECLARATIONS + (
    b"    const requireApiTokenOnLoopback = "
    b"['1', 'true', 'yes', 'on'].includes(String(process.env.OD_REQUIRE_API_TOKEN_ON_LOOPBACK ?? '')"
    b".trim().toLowerCase());\n"
)
_LOOPBACK_BYPASS = (
    b"            if (isLoopbackPeerAddress(req.socket?.remoteAddress))\n"
    b"                return next();\n"
)
_PATCHED_LOOPBACK_BYPASS = (
    b"            if (!requireApiTokenOnLoopback && isLoopbackPeerAddress(req.socket?.remoteAddress))\n"
    b"                return next();\n"
)

def apply_boundary_patch(stage: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    policy = manifest["boundary_patch"]
    target = stage.joinpath(*policy["path"].split("/"))
    try:
        target.resolve(strict=True).relative_to(stage.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise BoundaryPatchError("OpenDesign boundary patch target escapes the derived stage") from exc
    if target.is_symlink() or not target.is_file():
        raise BoundaryPatchError("OpenDesign boundary patch target must be a real file")
    source = target.read_bytes()
    pre_sha256 = hashlib.sha256(source).hexdigest()
    if pre_sha256 != policy["pre_sha256"]:
        raise BoundaryPatchError("OpenDesign boundary patch preimage does not match the authorized release")
    if source.count(_TOKEN_DECLARATIONS) != 1 or source.count(_LOOPBACK_BYPASS) != 1:
        raise BoundaryPatchError("OpenDesign boundary patch semantic preimage is missing or ambiguous")
    patched = source.replace(_TOKEN_DECLARATIONS, _PATCHED_TOKEN_DECLARATIONS, 1)
    patched = patched.replace(_LOOPBACK_BYPASS, _PATCHED_LOOPBACK_BYPASS, 1)
    if patched == source or patched.count(_PATCHED_LOOPBACK_BYPASS) != 1:
        raise BoundaryPatchError("OpenDesign boundary patch did not produce the authorized transformation")
    post_sha256 = hashlib.sha256(patched).hexdigest()
    expected_post = policy.get("post_sha256")
    if expected_post is not None and post_sha256 != expected_post:
        raise BoundaryPatchError("OpenDesign boundary patch postimage does not match the pin")
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, target.stat().st_mode & 0o777)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(patched)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    evidence: dict[str, Any] = {
        "path": policy["path"],
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "required_environment": policy["required_environment"],
    }
    return evidence


__all__ = ["BoundaryPatchError", "apply_boundary_patch"]
