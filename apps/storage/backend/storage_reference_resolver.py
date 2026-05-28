"""Stable Storage reference resolver."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import StorageValidationError
from inventory import resolve_file_record


@dataclass(frozen=True)
class StorageReferenceResolver:
    """Resolve stable Storage file ids without exposing provider internals."""

    data_root: Path
    uploaded_root: Path
    generated_root: Path

    def resolve_file(self, file_id: str) -> dict[str, Any] | None:
        return resolve_file_record(
            data_root=self.data_root,
            uploaded_root=self.uploaded_root,
            generated_root=self.generated_root,
            entity_id=file_id,
        )

    def require_file(self, file_id: str) -> dict[str, Any]:
        record = self.resolve_file(file_id)
        if record is None:
            raise StorageValidationError("File does not exist.")
        return record
