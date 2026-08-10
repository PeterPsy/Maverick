"""Atomic project lifecycle, duplication, and native interchange."""

from __future__ import annotations

from typing import Any

from project_ir import ProjectIR
from project_ir.canonical import content_digest

from .errors import ProjectError
from .repository_records import enqueue_event, set_archived
from .service_support import event_payload, identifier, project_name, revision_identity, validated_document


class ProjectLifecycleMixin:
    def create_project(
        self,
        *,
        name: str,
        project_id: str | None = None,
        description: str = "",
        actor: dict[str, str] | None = None,
        project_ir: object | None = None,
    ) -> dict[str, Any]:
        target_id = identifier(project_id or f"project-{self.id_factory()}", field="project_id")
        clean_name = project_name(name)
        if not isinstance(description, str) or len(description) > 4000:
            raise ProjectError("project_description_invalid", "Project description is invalid.")
        active_actor = _actor(actor)
        ir = (
            ProjectIR.empty(project_id=target_id, workspace_id=self.workspace_id, name=clean_name)
            if project_ir is None
            else validated_document(
                project_ir,
                workspace_id=self.workspace_id,
                project_id=target_id,
                name=clean_name,
            )
        )
        document = ir.to_dict()
        revision_id, digest = revision_identity(document)
        timestamp = self.clock()
        with self.repository.transaction() as connection:
            self.repository.insert_project(
                connection,
                project_id=target_id,
                name=clean_name,
                description=description,
                timestamp=timestamp,
            )
            self.repository.insert_revision(
                connection,
                revision_id=revision_id,
                project_id=target_id,
                parent_revision_id=None,
                document=document,
                operation_batch={"type": "project.create"},
                actor=active_actor,
                digest=digest,
                message="Project created",
                timestamp=timestamp,
            )
            self.repository.initialize_head(
                connection,
                project_id=target_id,
                revision_id=revision_id,
                document=document,
                timestamp=timestamp,
            )
            enqueue_event(
                connection,
                project_id=target_id,
                revision_id=revision_id,
                event_type="project.created",
                resource="projects",
                payload=event_payload(target_id, revision_id, "created"),
                timestamp=timestamp,
                dedupe_key=revision_id,
            )
        return self.get_project(target_id)

    def duplicate_project(
        self,
        source_project_id: str,
        *,
        name: str,
        project_id: str | None = None,
        actor: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        source = self.get_project(source_project_id)
        return self.create_project(
            name=name,
            project_id=project_id,
            description=f"Duplicated from {source_project_id}",
            actor=actor,
            project_ir=source["project_ir"],
        )

    def archive_project(self, project_id: str) -> dict[str, Any]:
        return self._set_archive(project_id, archived=True)

    def restore_project(self, project_id: str) -> dict[str, Any]:
        return self._set_archive(project_id, archived=False)

    def _set_archive(self, project_id: str, *, archived: bool) -> dict[str, Any]:
        target_id = identifier(project_id, field="project_id")
        timestamp = self.clock()
        with self.repository.transaction() as connection:
            project = self.repository.get_project(target_id, connection)
            changed = set_archived(
                connection,
                project_id=target_id,
                archived_at=timestamp if archived else None,
                timestamp=timestamp,
            )
            if changed:
                change = "archived" if archived else "restored"
                enqueue_event(
                    connection,
                    project_id=target_id,
                    revision_id=project["head_revision_id"],
                    event_type=f"project.{change}",
                    resource="projects",
                    payload=event_payload(target_id, project["head_revision_id"], change),
                    timestamp=timestamp,
                    dedupe_key=f"{change}:{timestamp}",
                )
        return self.repository.get_project(target_id)

    def export_native(self, project_id: str, revision_id: str | None = None) -> dict[str, Any]:
        project = self.repository.get_project(identifier(project_id, field="project_id"))
        selected = revision_id or project["head_revision_id"]
        revision = self.get_revision(project_id, selected)
        return {
            "format": "video-studio-native.v1",
            "project": {"project_id": project_id, "name": project["name"], "description": project["description"]},
            "revision": {
                "revision_id": selected,
                "digest": revision["digest"],
                "project_ir": revision["project_ir"],
            },
        }

    def import_native(
        self,
        payload: object,
        *,
        project_id: str | None = None,
        name: str | None = None,
        actor: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != {"format", "project", "revision"}:
            raise ProjectError("native_import_invalid", "Native import envelope is invalid.")
        if payload.get("format") != "video-studio-native.v1":
            raise ProjectError("native_import_version_unsupported", "Native import version is unsupported.")
        project, revision = payload.get("project"), payload.get("revision")
        if not isinstance(project, dict) or set(project) != {"project_id", "name", "description"}:
            raise ProjectError("native_import_invalid", "Native project metadata is invalid.")
        if not isinstance(revision, dict) or set(revision) != {"revision_id", "digest", "project_ir"}:
            raise ProjectError("native_import_invalid", "Native revision envelope is invalid.")
        document = validated_document(revision["project_ir"], workspace_id=self.workspace_id)
        if content_digest(document.to_dict()) != revision.get("digest"):
            raise ProjectError("native_import_digest_mismatch", "Native revision digest does not match its content.")
        return self.create_project(
            name=name or project["name"],
            project_id=project_id or project["project_id"],
            description=project["description"],
            actor=actor,
            project_ir=document.to_dict(),
        )


def _actor(value: dict[str, str] | None) -> dict[str, str]:
    actor = value or {"kind": "system", "id": "video-studio"}
    if not isinstance(actor, dict) or set(actor) != {"kind", "id"}:
        raise ProjectError("actor_invalid", "Actor must contain kind and id.")
    if actor.get("kind") not in {"user", "agent", "system"}:
        raise ProjectError("actor_kind_invalid", "Actor kind is unsupported.")
    return {"kind": str(actor["kind"]), "id": identifier(actor.get("id"), field="actor/id")}
