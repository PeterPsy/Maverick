"""Project service construction and read-only revision surfaces."""

from __future__ import annotations

from pathlib import Path
from contextlib import closing
from typing import Any

from foundation.database import FoundationDatabase

from .repository import ProjectRepository
from .repository_records import pending_events
from .revision_diff import compare_values
from .service_support import Clock, IdFactory, identifier, random_id, utc_now


class ProjectServiceCore:
    def __init__(
        self,
        data_root: str | Path,
        *,
        workspace_id: str,
        clock: Clock = utc_now,
        id_factory: IdFactory = random_id,
    ) -> None:
        self.workspace_id = identifier(workspace_id, field="workspace_id")
        self.clock = clock
        self.id_factory = id_factory
        self.database = FoundationDatabase(data_root)
        self.database.migrate()
        self.repository = ProjectRepository(self.database)

    def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        return self.repository.list_projects(include_archived=include_archived)

    def get_project(self, project_id: str) -> dict[str, Any]:
        project = self.repository.get_project(identifier(project_id, field="project_id"))
        revision = self.repository.get_revision(project_id, project["head_revision_id"])
        return {**project, "project_ir": revision["project_ir"], "digest": revision["digest"]}

    def get_revision(self, project_id: str, revision_id: str) -> dict[str, Any]:
        return self.repository.get_revision(
            identifier(project_id, field="project_id"),
            identifier(revision_id, field="revision_id"),
        )

    def compare_revisions(
        self,
        project_id: str,
        before_revision_id: str,
        after_revision_id: str,
    ) -> dict[str, Any]:
        before = self.get_revision(project_id, before_revision_id)
        after = self.get_revision(project_id, after_revision_id)
        changes = compare_values(before["project_ir"], after["project_ir"])
        return {
            "project_id": project_id,
            "before_revision_id": before_revision_id,
            "after_revision_id": after_revision_id,
            "changes": changes,
            "change_count": len(changes),
        }

    def pending_outbox(self) -> list[dict[str, Any]]:
        with closing(self.database.connect(read_only=True)) as connection:
            return pending_events(connection)
