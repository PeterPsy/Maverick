"""Workspace-scoped JSON collections for runtime records."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from core.runtime.paths import workspace_runtime_root
from core.shared.json_file_collection import JsonFileCollection


class WorkspaceRuntimeJsonCollection:
    """Persist workspace-scoped runtime records under each workspace runtime root."""

    def __init__(self, *, start_path: Path, filename: str) -> None:
        self.start_path = start_path
        self.filename = filename

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for path in self._candidate_paths(query):
            collection = JsonFileCollection(path)
            for document in collection.find(query):
                return deepcopy(document)
        return None

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for path in self._candidate_paths(query):
            collection = JsonFileCollection(path)
            matches.extend(collection.find(query))
        return matches

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> None:
        payload = deepcopy(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"Runtime {self.filename} updates require workspace_id.")
        JsonFileCollection(self._record_path(workspace_id)).update_one(query, update, upsert=upsert)

    def compare_and_set(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        """Apply an exact conditional update inside one workspace partition."""
        payload = deepcopy(update.get("$set", {}))
        workspace_id = str(payload.get("workspace_id") or query.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"Runtime {self.filename} compare-and-set requires workspace_id.")
        return JsonFileCollection(self._record_path(workspace_id)).compare_and_set(query, update)

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert one workspace-scoped record atomically when no existing record matches."""
        payload = {**deepcopy(query), **deepcopy(document)}
        workspace_id = str(payload.get("workspace_id") or "").strip()
        if not workspace_id:
            raise ValueError(f"Runtime {self.filename} inserts require workspace_id.")
        return JsonFileCollection(self._record_path(workspace_id)).insert_one_if_absent(query, payload)

    def delete_one(self, query: dict[str, Any]) -> None:
        for path in self._candidate_paths(query):
            collection = JsonFileCollection(path)
            if collection.find_one(query) is None:
                continue
            collection.delete_one(query)
            return

    def delete_many(self, query: dict[str, Any]) -> int:
        return len(self.delete_many_documents(query))

    def delete_many_documents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        deleted: list[dict[str, Any]] = []
        for path in self._candidate_paths(query):
            deleted.extend(JsonFileCollection(path).delete_many_documents(query))
        return deleted

    def _candidate_paths(self, query: dict[str, Any]) -> list[Path]:
        workspace_id = str(query.get("workspace_id") or "").strip()
        if workspace_id:
            return [self._record_path(workspace_id)]
        return sorted((self.start_path / "workspaces").glob(f"*/runtime/{self.filename}"))

    def _record_path(self, workspace_id: str) -> Path:
        return workspace_runtime_root(workspace_id=workspace_id, start_path=self.start_path) / self.filename
