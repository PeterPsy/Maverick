"""Fixture-only, fail-closed launcher phase failure injection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat

from opendesign_artifact import write_canonical_json


FAILURE_INJECTION_ROOT_ENV = "MAVERICK_OPENDESIGN_FAILURE_INJECTION_ROOT"
FAILURE_INJECTION_PHASES = frozenset({"browser_prewarm", "readiness_commit"})


class FailureInjectionError(RuntimeError):
    """Typed fixture failure safe to persist in launcher status."""

    def __init__(self, code: str, phase: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.phase = phase


def inject_test_failure(
    generation_root: Path,
    *,
    startup_id: str,
    phase: str,
) -> None:
    """Consume one fixture-only request and terminate at an exact launch phase.

    Production contracts do not export ``FAILURE_INJECTION_ROOT_ENV``. The
    release fixture uses an isolated copy of the app contract to opt in, so a
    workspace file cannot activate this path in a deployed installation.
    """
    configured = str(os.environ.get(FAILURE_INJECTION_ROOT_ENV) or "").strip()
    if not configured:
        return
    if phase not in FAILURE_INJECTION_PHASES:
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection phase is invalid",
        )
    root = Path(configured)
    expected = generation_root / ".maverick-failure-injection"
    if not root.is_absolute() or root.resolve(strict=False) != expected.resolve(strict=False):
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection root is outside the generation",
        )
    if not root.exists() and not root.is_symlink():
        return
    try:
        root_metadata = root.lstat()
    except OSError as error:
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection root is unavailable",
        ) from error
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_IMODE(root_metadata.st_mode) & 0o077
    ):
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection root is unsafe",
        )
    request = root / "request.json"
    if not request.exists() and not request.is_symlink():
        return
    try:
        metadata = request.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size < 1
            or metadata.st_size > 4096
        ):
            raise OSError("failure injection request is not private")
        payload = json.loads(request.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection request is invalid",
        ) from error
    expected_keys = {"schema_version", "phase", "action", "nonce"}
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection request schema is invalid",
        )
    requested_phase = payload.get("phase")
    if requested_phase not in FAILURE_INJECTION_PHASES:
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection request phase is invalid",
        )
    if requested_phase != phase:
        return
    nonce = payload.get("nonce")
    if (
        payload.get("schema_version") != "1"
        or payload.get("action") != "sigkill"
        or not isinstance(nonce, str)
        or len(nonce) != 32
        or any(character not in "0123456789abcdef" for character in nonce)
    ):
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection request identity is invalid",
        )
    consumed = root / f"consumed-{nonce}.json"
    observed = root / f"observed-{nonce}.json"
    if consumed.exists() or consumed.is_symlink() or observed.exists() or observed.is_symlink():
        raise FailureInjectionError(
            "runtime_binding_invalid",
            "failure_injection",
            "OpenDesign failure injection nonce was already consumed",
        )
    try:
        os.replace(request, consumed)
        write_canonical_json(
            observed,
            {
                "schema_version": "1",
                "phase": phase,
                "action": "sigkill",
                "nonce": nonce,
                "startup_id": startup_id,
            },
        )
        observed.chmod(0o600)
        descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise FailureInjectionError(
            "activation_incomplete",
            "failure_injection",
            "OpenDesign failure injection could not persist its phase proof",
        ) from error
    os.kill(os.getpid(), signal.SIGKILL)
    raise FailureInjectionError(
        "activation_incomplete",
        "failure_injection",
        "OpenDesign failure injection did not terminate the launcher",
    )
