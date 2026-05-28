"""Local filesystem provider for Storage Uploaded and Generated roots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from inventory import catalog_inventory_payload, list_inventory_folders, resolve_file_record


@dataclass(frozen=True)
class LocalStorageProvider:
    """Provider adapter for workspace-local storage roots."""

    uploaded_root: Path
    generated_root: Path

    provider: str = "local"

    def catalog(
        self,
        *,
        data_root: Path,
        sync: bool = False,
        query: str = "",
        role: str = "all",
        kind: str = "all",
        offset: int = 0,
        limit: int | None = None,
        sort_by: str = "modified_at",
        sort_direction: str = "desc",
        folder_path: str | None = None,
        file_ids: list[str] | None = None,
        workspace_relative_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        return catalog_inventory_payload(
            data_root=data_root,
            uploaded_root=self.uploaded_root,
            generated_root=self.generated_root,
            sync=sync,
            query=query,
            role=role,
            kind=kind,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            sort_direction=sort_direction,
            folder_path=folder_path,
            file_ids=file_ids,
            workspace_relative_paths=workspace_relative_paths,
        )

    def list_folders(self, *, data_root: Path, sync: bool = False) -> list[dict[str, Any]]:
        return list_inventory_folders(
            data_root=data_root,
            uploaded_root=self.uploaded_root,
            generated_root=self.generated_root,
            sync=sync,
        )

    def resolve_file(self, *, data_root: Path, file_id: str) -> dict[str, Any] | None:
        return resolve_file_record(
            data_root=data_root,
            uploaded_root=self.uploaded_root,
            generated_root=self.generated_root,
            entity_id=file_id,
        )
