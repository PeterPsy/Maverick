"""Observed private artifacts and a durable index, never automatic verdicts."""

import base64
from dataclasses import asdict, is_dataclass
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path

from core.certification_lab.errors import LabAuthorizationError
from core.certification_lab.private_files import require_private_path
from core.providers.evidence_store import CapabilityEvidenceBlobStore


class LabEvidenceRecorder:
    def __init__(self, operator_root: Path, *, session_id: str):
        from core.runtime.paths import normalize_runtime_session_id

        self.index = operator_root / f'observations-{normalize_runtime_session_id(session_id)}.jsonl'
        require_private_path(self.index, must_exist=self.index.exists())
        self.blobs = CapabilityEvidenceBlobStore(operator_root / 'evidence')

    def record(self, kind: str, value: object) -> str:
        content = json.dumps(_observed_json(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        ref = self.blobs.put(content)
        row = json.dumps({'kind': kind, 'evidence_ref': ref}, sort_keys=True).encode() + b'\n'
        require_private_path(self.index, must_exist=self.index.exists())
        fd = os.open(self.index, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab', buffering=0) as output:
            fcntl.flock(output.fileno(), fcntl.LOCK_EX)
            output.write(row)
            os.fsync(output.fileno())
        return ref

    def observations(self):
        from core.certification_lab.private_files import read_private_file

        rows = [json.loads(line) for line in read_private_file(self.index, max_bytes=1_048_576).splitlines()]
        for row in rows:
            self.blobs.get(row['evidence_ref'])
        return tuple(rows)


def _observed_json(value):
    if is_dataclass(value):
        return _observed_json(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return {'encoding': 'base64', 'content': base64.b64encode(value).decode()}
    if isinstance(value, dict):
        return {str(key): _observed_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_observed_json(item) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    # In particular, never stringify an unknown credential or private object.
    raise LabAuthorizationError('lab_observation_type_invalid')
