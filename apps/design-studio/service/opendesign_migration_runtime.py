"""Governed runtime boundary and outcomes for OpenDesign migration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from opendesign_generation_model import GenerationControl, GenerationTriple


class MigrationError(RuntimeError):
    """Raised when a controlled migration cannot complete safely."""


class MigrationRuntime(Protocol):
    """App-owned boundary that drives only governed OpenDesign operations."""

    def freeze_mutations(self) -> None: ...

    def unfreeze_mutations(self) -> None: ...

    def drain_or_cancel_runs(self) -> None: ...

    def stop_sidecar(self) -> None: ...

    def prove_sidecar_stopped(self, data_dir: Path) -> None: ...

    def start_sidecar(self, triple: GenerationTriple, data_dir: Path, *, staging: bool) -> None: ...

    def health_check(self) -> None: ...

    def verify_database(self) -> None: ...

    def list_project_ids(self) -> list[str]: ...

    def smoke_project(self, project_id: str) -> None: ...

    def create_legacy_project(self, project: Mapping[str, object], *, idempotency_key: str) -> str: ...

    def upload_legacy_import(
        self,
        project_id: str,
        *,
        name: str,
        media_type: str,
        content: bytes,
        sha256: str,
    ) -> None: ...


@dataclass(frozen=True)
class MigrationOutcome:
    migration_id: str
    control: GenerationControl
    mapping_sha256: str
    migrated_projects: int
    migrated_imports: int


@dataclass(frozen=True)
class RecoveryOutcome:
    control: GenerationControl
    reconciliations: tuple[str, ...]
    journal_completed: bool
