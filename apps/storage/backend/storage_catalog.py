"""Normalized Storage catalog orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_storage_provider import LocalStorageProvider


@dataclass(frozen=True)
class StorageCatalog:
    """Catalog facade that keeps provider adapters out of request handling."""

    local_provider: LocalStorageProvider

    def catalog_files(
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
        return self.local_provider.catalog(
            data_root=data_root,
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
        return self.local_provider.list_folders(data_root=data_root, sync=sync)
