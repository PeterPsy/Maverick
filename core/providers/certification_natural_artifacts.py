"""Private artifact helpers shared by natural-certification operators."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class OpenRouterNaturalOperatorConfig:
    repository_root: Path
    job_root: Path
    control_root: Path
    source_commit: str
    ledger_path: Path
    ledger_policy_digest: str
    reviewer_ref: str
    signer_key_id: str
    signer_key_path: Path


def artifact_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


def write_new_json(path: Path, value: object) -> str:
    data = json.dumps(
        jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return artifact_sha256(data)


__all__ = [
    "OpenRouterNaturalOperatorConfig",
    "artifact_sha256",
    "jsonable",
    "write_new_json",
]
