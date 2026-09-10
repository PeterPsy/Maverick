"""Isolated fixture execution and redaction-safe certification failure records."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping

from core.providers.errors import CapabilityCertificateError


FAILURE_ARTIFACT_SCHEMA = "maverick.agentic-certification-failure.v1"
_SAFE_HOST_ENVIRONMENT_KEYS = frozenset({"PATH", "LANG", "LANGUAGE", "TZ"})
_REASON_CODE_PATTERN = re.compile(
    r"(?:reason_code[\"']?\s*[:=]\s*[\"']?|(?:Certificate|Protocol|StructuredCli)Error:\s*)"
    r"([a-z][a-z0-9_]{1,95})"
)
_EXCEPTION_TYPE_PATTERN = re.compile(
    r"(?m)^([A-Za-z_][A-Za-z0-9_.]{0,127}(?:Error|Exception))(?::|$)"
)
_FAILED_TEST_PATTERN = re.compile(
    r"(?m)^(?:FAIL|ERROR): [^\r\n]{1,256} "
    r"\(((?:[A-Za-z_][A-Za-z0-9_]*\.){2,}[A-Za-z_][A-Za-z0-9_]*)\)$"
)
_RAN_TESTS_PATTERN = re.compile(r"(?m)^Ran ([0-9]{1,7}) tests? in ")
_UNITTEST_FAILURE_COUNTS_PATTERN = re.compile(
    r"(?:^|, )(failures|errors|skipped)=([0-9]{1,7})(?=,|$)"
)
_SAFE_DIAGNOSTIC_FIELDS = frozenset(
    {
        "reason_code",
        "failure_diagnostic",
        "request_count",
        "filesystem_result_count",
        "succeeded",
    }
)
_MAX_DIAGNOSTIC_INPUT_BYTES = 16_384
_MAX_DIAGNOSTIC_SCAN_BYTES = 65_536


def fixture_contract_environment(
    source: Mapping[str, str],
    *,
    run_nonce: str,
    private_root: Path,
) -> dict[str, str]:
    """Build a synthetic environment with no production authority or secret."""
    environment = {
        key: str(value)
        for key, value in source.items()
        if key in _SAFE_HOST_ENVIRONMENT_KEYS or key.startswith("LC_")
    }
    home = private_root / "home"
    temporary = private_root / "tmp"
    for directory in (
        home / ".codex",
        temporary,
        private_root / "cache",
        private_root / "config",
        private_root / "data",
    ):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "TMP": str(temporary),
            "TEMP": str(temporary),
            "XDG_CACHE_HOME": str(private_root / "cache"),
            "XDG_CONFIG_HOME": str(private_root / "config"),
            "XDG_DATA_HOME": str(private_root / "data"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
            "MAVERICK_ADMIN_USERNAME": "admin",
            "MAVERICK_CERTIFICATION_ALLOW_LIVE": "0",
            "MAVERICK_CERTIFICATION_RUN_NONCE": run_nonce,
        }
    )
    return environment


def write_step_failure_artifact(
    path: Path | None,
    *,
    source_root: Path,
    suite_id: str,
    suite_version: str,
    source_commit: str,
    target_digest: str,
    tcb_manifest_version: str,
    tcb_live_digest: str,
    step_id: str,
    step_kind: str,
    command_digest: str,
    exit_code: int | None,
    failure_reason: str,
    stdout: bytes,
    stderr: bytes,
) -> None:
    """Write hashes and allowlisted diagnostics, never raw subprocess output."""
    if path is None:
        return
    destination = _validated_new_artifact_path(path, source_root=source_root)
    diagnostic = _safe_diagnostic(stdout=stdout, stderr=stderr)
    payload = {
        "schema_version": FAILURE_ARTIFACT_SCHEMA,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
        "suite_id": suite_id,
        "suite_version": suite_version,
        "source_commit": source_commit,
        "target_digest": target_digest,
        "tcb_manifest_version": tcb_manifest_version,
        "tcb_live_digest": tcb_live_digest,
        "step_id": step_id,
        "step_kind": step_kind,
        "command_digest": command_digest,
        "exit_code": exit_code,
        "failure_reason": failure_reason,
        "stdout_bytes": len(stdout),
        "stdout_digest": hashlib.sha256(stdout).hexdigest(),
        "stderr_bytes": len(stderr),
        "stderr_digest": hashlib.sha256(stderr).hexdigest(),
        "diagnostic": diagnostic,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)


def validate_failure_artifact_path(path: Path | None, *, source_root: Path) -> None:
    """Reject source-owned, existing, symlinked, or unavailable destinations."""
    if path is not None:
        _validated_new_artifact_path(path, source_root=source_root)


def _validated_new_artifact_path(path: Path, *, source_root: Path) -> Path:
    candidate = Path(path)
    try:
        source = source_root.resolve(strict=True)
        parent = candidate.parent.resolve(strict=True)
    except OSError as error:
        raise CapabilityCertificateError("certification_failure_artifact_path_invalid") from error
    destination = parent / candidate.name
    try:
        destination.resolve(strict=False).relative_to(source)
    except ValueError:
        pass
    else:
        raise CapabilityCertificateError("certification_failure_artifact_path_invalid")
    if not candidate.name or destination.exists() or destination.is_symlink():
        raise CapabilityCertificateError("certification_failure_artifact_path_invalid")
    return destination


def _safe_diagnostic(*, stdout: bytes, stderr: bytes) -> dict[str, object]:
    reason_codes: set[str] = set()
    exception_types: set[str] = set()
    failed_tests: set[str] = set()
    safe_json: dict[str, object] = {}
    bounded_stdout = stdout[:_MAX_DIAGNOSTIC_INPUT_BYTES]
    if len(stdout) <= _MAX_DIAGNOSTIC_INPUT_BYTES:
        try:
            value = json.loads(bounded_stdout.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            value = None
        if isinstance(value, dict):
            for key in _SAFE_DIAGNOSTIC_FIELDS:
                field = value.get(key)
                if key == "reason_code" and isinstance(field, str) and _safe_reason_code(field):
                    reason_codes.add(field)
                    safe_json[key] = field
                elif (
                    key == "failure_diagnostic"
                    and isinstance(field, str)
                    and _safe_reason_code(field)
                ):
                    safe_json[key] = field
                elif key in {"request_count", "filesystem_result_count"} and type(field) is int:
                    safe_json[key] = field
                elif key == "succeeded" and type(field) is bool:
                    safe_json[key] = field
    unittest_summary: dict[str, int] = {}
    for raw in (_diagnostic_scan(stdout), _diagnostic_scan(stderr)):
        text = raw.decode("utf-8", errors="replace")
        reason_codes.update(
            match.group(1) for match in _REASON_CODE_PATTERN.finditer(text)
            if _safe_reason_code(match.group(1))
        )
        exception_types.update(
            match.group(1) for match in _EXCEPTION_TYPE_PATTERN.finditer(text)
        )
        failed_tests.update(
            match.group(1) for match in _FAILED_TEST_PATTERN.finditer(text)
        )
        ran = tuple(_RAN_TESTS_PATTERN.finditer(text))
        if ran:
            unittest_summary["tests"] = int(ran[-1].group(1))
        for line in re.findall(r"(?m)^FAILED \(([^\r\n]{1,256})\)$", text):
            for match in _UNITTEST_FAILURE_COUNTS_PATTERN.finditer(line):
                unittest_summary[match.group(1)] = int(match.group(2))
    return {
        "reason_codes": sorted(reason_codes),
        "exception_types": sorted(exception_types),
        "failed_tests": sorted(failed_tests),
        "safe_json": safe_json,
        "unittest_summary": unittest_summary,
        "stdout_truncated": len(stdout) > _MAX_DIAGNOSTIC_SCAN_BYTES,
        "stderr_truncated": len(stderr) > _MAX_DIAGNOSTIC_SCAN_BYTES,
    }


def _safe_reason_code(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{1,95}", value))


def _diagnostic_scan(value: bytes) -> bytes:
    if len(value) <= _MAX_DIAGNOSTIC_SCAN_BYTES:
        return value
    half = _MAX_DIAGNOSTIC_SCAN_BYTES // 2
    return value[:half] + b"\n" + value[-half:]


__all__ = [
    "FAILURE_ARTIFACT_SCHEMA",
    "fixture_contract_environment",
    "validate_failure_artifact_path",
    "write_step_failure_artifact",
]
