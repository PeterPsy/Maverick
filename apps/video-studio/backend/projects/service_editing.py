"""Transactional operation batches and persistent revision navigation."""

from __future__ import annotations

from typing import Any

from .batches import OperationBatch
from .errors import ProjectError, stale_revision
from .operations import apply_operation_batch
from .repository_records import enqueue_event, record_autosave, record_batch
from .service_support import event_payload, revision_identity


class ProjectEditingMixin:
    def apply_operations(self, payload: object) -> dict[str, Any]:
        batch = OperationBatch.parse(payload, trusted_workspace_id=self.workspace_id)
        timestamp = self.clock()
        with self.repository.transaction() as connection:
            project = self.repository.get_project(batch.project_id, connection)
            cached = self.repository.idempotency_result(
                connection,
                batch.project_id,
                batch.operation_batch_id,
                batch.request_digest,
            )
            if cached is not None:
                return cached
            _editable(project)
            if project["head_revision_id"] != batch.base_revision_id:
                raise stale_revision(batch.base_revision_id, project["head_revision_id"])
            base = self.repository.get_revision(batch.project_id, batch.base_revision_id, connection)
            document, applied = apply_operation_batch(base["project_ir"], batch)
            revision_id, digest = revision_identity(document)
            self.repository.insert_revision(
                connection,
                revision_id=revision_id,
                project_id=batch.project_id,
                parent_revision_id=batch.base_revision_id,
                document=document,
                operation_batch=batch.request,
                actor=batch.actor,
                digest=digest,
                message=str(batch.metadata.get("message", "")),
                timestamp=timestamp,
            )
            self.repository.update_head(
                connection,
                project_id=batch.project_id,
                expected_revision_id=batch.base_revision_id,
                revision_id=revision_id,
                document=document,
                timestamp=timestamp,
            )
            undo, _ = self.repository.navigation(connection, batch.project_id)
            self.repository.write_navigation(
                connection,
                batch.project_id,
                [*undo, batch.base_revision_id],
                [],
                timestamp,
            )
            result = _result(batch, revision_id, digest, applied)
            self._record_edit(connection, batch, result, revision_id, timestamp)
        return result

    def rename_project(
        self,
        project_id: str,
        *,
        name: str,
        base_revision_id: str,
        operation_batch_id: str,
        actor: dict[str, str],
    ) -> dict[str, Any]:
        return self.apply_operations(
            {
                "workspace_id": self.workspace_id,
                "project_id": project_id,
                "base_revision_id": base_revision_id,
                "operation_batch_id": operation_batch_id,
                "preconditions": [{"type": "head_is", "revision_id": base_revision_id}],
                "actor": actor,
                "operations": [{"type": "project.rename", "name": name}],
                "autosave": {"enabled": False, "reason": "rename"},
                "metadata": {"message": "Project renamed"},
            }
        )

    def undo(self, payload: object) -> dict[str, Any]:
        return self._navigate(payload, direction="undo")

    def redo(self, payload: object) -> dict[str, Any]:
        return self._navigate(payload, direction="redo")

    def _navigate(self, payload: object, *, direction: str) -> dict[str, Any]:
        batch = OperationBatch.parse(payload, trusted_workspace_id=self.workspace_id)
        expected_operation = {"type": f"history.{direction}"}
        if tuple(batch.operations) != (expected_operation,):
            raise ProjectError("history_operation_invalid", f"{direction.capitalize()} requires one typed history operation.")
        timestamp = self.clock()
        with self.repository.transaction() as connection:
            project = self.repository.get_project(batch.project_id, connection)
            cached = self.repository.idempotency_result(
                connection,
                batch.project_id,
                batch.operation_batch_id,
                batch.request_digest,
            )
            if cached is not None:
                return cached
            _editable(project)
            if project["head_revision_id"] != batch.base_revision_id:
                raise stale_revision(batch.base_revision_id, project["head_revision_id"])
            undo, redo = self.repository.navigation(connection, batch.project_id)
            source, destination = (undo, redo) if direction == "undo" else (redo, undo)
            if not source:
                raise ProjectError(f"{direction}_unavailable", f"No persistent {direction} revision is available.", status_code=409)
            target_revision_id = source.pop()
            target = self.repository.get_revision(batch.project_id, target_revision_id, connection)
            destination.append(batch.base_revision_id)
            self.repository.update_head(
                connection,
                project_id=batch.project_id,
                expected_revision_id=batch.base_revision_id,
                revision_id=target_revision_id,
                document=target["project_ir"],
                timestamp=timestamp,
            )
            self.repository.write_navigation(connection, batch.project_id, undo, redo, timestamp)
            result = _result(batch, target_revision_id, target["digest"], (f"history.{direction}",))
            self._record_edit(connection, batch, result, target_revision_id, timestamp)
        return result

    def _record_edit(
        self,
        connection: Any,
        batch: OperationBatch,
        result: dict[str, Any],
        revision_id: str,
        timestamp: str,
    ) -> None:
        record_batch(
            connection,
            project_id=batch.project_id,
            batch_id=batch.operation_batch_id,
            workspace_id=batch.workspace_id,
            base_revision_id=batch.base_revision_id,
            request_digest=batch.request_digest,
            result_revision_id=revision_id,
            result=result,
            timestamp=timestamp,
        )
        if batch.autosave["enabled"]:
            record_autosave(
                connection,
                project_id=batch.project_id,
                batch_id=batch.operation_batch_id,
                revision_id=revision_id,
                metadata={"reason": batch.autosave["reason"], "batch_metadata": batch.metadata},
                timestamp=timestamp,
            )
        enqueue_event(
            connection,
            project_id=batch.project_id,
            revision_id=revision_id,
            event_type="project.revision.changed",
            resource="revisions",
            payload=event_payload(batch.project_id, revision_id, "revision"),
            timestamp=timestamp,
            dedupe_key=batch.operation_batch_id,
        )
        if any(operation["type"] == "project.rename" for operation in batch.operations):
            enqueue_event(
                connection,
                project_id=batch.project_id,
                revision_id=revision_id,
                event_type="project.metadata.updated",
                resource="project-metadata",
                payload=event_payload(batch.project_id, revision_id, "metadata"),
                timestamp=timestamp,
                dedupe_key=batch.operation_batch_id,
            )


def _result(
    batch: OperationBatch,
    revision_id: str,
    digest: str,
    operations: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "workspace_id": batch.workspace_id,
        "project_id": batch.project_id,
        "operation_batch_id": batch.operation_batch_id,
        "base_revision_id": batch.base_revision_id,
        "revision_id": revision_id,
        "digest": digest,
        "applied_operations": list(operations),
    }


def _editable(project: dict[str, Any]) -> None:
    if project["archived_at"] is not None:
        raise ProjectError("project_archived", "Archived projects cannot be edited.", status_code=409)
