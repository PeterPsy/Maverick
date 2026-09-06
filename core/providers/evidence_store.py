"""Content-addressed platform store for capability certification evidence."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from core.providers.errors import CapabilityCertificateError


DEFAULT_MAX_EVIDENCE_BLOB_BYTES = 8 * 1024 * 1024
EVIDENCE_REF_PREFIX = "platform-evidence:sha256:"


class CapabilityEvidenceBlobStore:
    """Create-if-absent evidence blobs outside workspace and app storage."""

    def __init__(self, root: Path, *, max_blob_bytes: int = DEFAULT_MAX_EVIDENCE_BLOB_BYTES) -> None:
        self.root = Path(root)
        self.max_blob_bytes = max_blob_bytes

    def put(self, content: bytes, *, expected_digest: str | None = None) -> str:
        """Persist bounded bytes by digest and return an opaque platform reference."""
        if not isinstance(content, bytes) or len(content) > self.max_blob_bytes:
            raise CapabilityCertificateError("certificate_evidence_blob_size_invalid")
        digest = hashlib.sha256(content).hexdigest()
        if expected_digest is not None and expected_digest != digest:
            raise CapabilityCertificateError("certificate_evidence_blob_digest_mismatch")
        target = self._path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if self._read_verified(target, digest) != content:
                raise CapabilityCertificateError("certificate_evidence_blob_immutable_conflict")
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return f"{EVIDENCE_REF_PREFIX}{digest}"

    def get(self, evidence_ref: str) -> bytes:
        """Read one opaque evidence reference with integrity verification."""
        digest = self._digest_from_ref(evidence_ref)
        path = self._path(digest)
        return self._read_verified(path, digest)

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def _read_verified(self, path: Path, digest: str) -> bytes:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise CapabilityCertificateError("certificate_evidence_blob_corrupt")
                content = handle.read(self.max_blob_bytes + 1)
        except FileNotFoundError as error:
            raise CapabilityCertificateError("certificate_evidence_blob_missing") from error
        except OSError as error:
            raise CapabilityCertificateError("certificate_evidence_blob_corrupt") from error
        if len(content) > self.max_blob_bytes or hashlib.sha256(content).hexdigest() != digest:
            raise CapabilityCertificateError("certificate_evidence_blob_corrupt")
        return content

    @staticmethod
    def _digest_from_ref(evidence_ref: str) -> str:
        value = str(evidence_ref or "")
        if not value.startswith(EVIDENCE_REF_PREFIX):
            raise CapabilityCertificateError("certificate_evidence_ref_invalid")
        digest = value[len(EVIDENCE_REF_PREFIX):]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise CapabilityCertificateError("certificate_evidence_ref_invalid")
        return digest
