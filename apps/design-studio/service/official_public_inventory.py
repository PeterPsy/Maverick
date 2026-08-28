"""Redaction-safe inventory of one disposable official OpenDesign data copy."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from official_inventory_process import OfficialApiClient, running_official_api
from official_inventory_values import (
    canonical_digest,
    category_digest,
    created_order,
    design_system_files,
    identifier,
    object_list,
    safe_file_path,
    stable_file,
    stable_project,
    stable_run,
    stable_value,
)
from official_opendesign_release import OfficialInstallation, OfficialReleaseError


def inventory_official_copy(
    installation: OfficialInstallation,
    *,
    data_dir: Path,
    log_path: Path,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """Run upstream migrations and inventory only through supported HTTP APIs."""
    with running_official_api(
        installation,
        data_dir=data_dir,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
    ) as client:
        inventory = _inventory(client)
    return {
        "schema_version": "1",
        "kind": "official-opendesign-public-inventory",
        "release": {
            "version": installation.release.version,
            "manifest_digest": installation.release.manifest_digest,
            "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
        },
        "categories": inventory,
        "semantic_content_retained": False,
        "private_database_read": False,
    }


def inventory_digest(inventory: dict[str, Any]) -> str:
    return canonical_digest(inventory)


def _inventory(client: OfficialApiClient) -> dict[str, dict[str, Any]]:
    projects_payload = client.get_json("/api/projects")
    projects = object_list(projects_payload, "projects")
    project_records: list[dict[str, Any]] = []
    conversation_records: list[dict[str, Any]] = []
    message_records: list[dict[str, Any]] = []
    file_records: list[dict[str, Any]] = []
    artifact_records: list[dict[str, Any]] = []
    run_references: list[dict[str, Any]] = []
    for project in sorted(projects, key=lambda item: str(item.get("id") or "")):
        project_id = identifier(project.get("id"), "project")
        detail = client.get_json(f"/api/projects/{quote(project_id, safe='')}")
        native_project = detail.get("project")
        if not isinstance(native_project, dict) or native_project.get("id") != project_id:
            raise OfficialReleaseError("official project detail identity mismatch")
        project_records.append(stable_project(native_project))
        status = project.get("status") if isinstance(project.get("status"), dict) else {}
        if status.get("runId"):
            run_references.append({
                "project_id": project_id,
                "run_id": status.get("runId"),
                "status": status.get("value"),
            })
        conversations = object_list(
            client.get_json(
                f"/api/projects/{quote(project_id, safe='')}/conversations",
            ),
            "conversations",
        )
        for conversation in sorted(conversations, key=created_order):
            conversation_id = identifier(conversation.get("id"), "conversation")
            conversation_records.append({
                "project_id": project_id,
                "conversation": stable_value(conversation),
            })
            messages = object_list(
                client.get_json(
                    "/api/projects/"
                    f"{quote(project_id, safe='')}/conversations/"
                    f"{quote(conversation_id, safe='')}/messages",
                ),
                "messages",
            )
            for index, message in enumerate(messages):
                message_records.append({
                    "project_id": project_id,
                    "conversation_id": conversation_id,
                    "order": index,
                    "message": stable_value(message),
                })
                if message.get("runId"):
                    run_references.append({
                        "project_id": project_id,
                        "conversation_id": conversation_id,
                        "message_id": message.get("id"),
                        "run_id": message.get("runId"),
                        "run_status": message.get("runStatus"),
                        "event_cursor": message.get("lastRunEventId"),
                    })
        files = object_list(
            client.get_json(
                f"/api/projects/{quote(project_id, safe='')}/files",
            ),
            "files",
        )
        for file_record in sorted(files, key=lambda item: str(item.get("path") or item.get("name") or "")):
            name = safe_file_path(file_record.get("path") or file_record.get("name"))
            body = client.get_bytes(
                f"/api/projects/{quote(project_id, safe='')}/files/{quote(name, safe='/')}",
            )
            file_records.append({
                "project_id": project_id,
                "name": name,
                "body_sha256": sha256(body).hexdigest(),
                "metadata": stable_file(file_record),
            })
            manifest = file_record.get("artifactManifest")
            if isinstance(manifest, dict):
                artifact_records.append({
                    "project_id": project_id,
                    "name": name,
                    "manifest": stable_value(manifest),
                })
        live_artifacts = object_list(
            client.get_json(f"/api/live-artifacts?projectId={quote(project_id, safe='')}"),
            "artifacts",
        )
        for artifact in sorted(live_artifacts, key=lambda item: str(item.get("id") or "")):
            artifact_id = identifier(artifact.get("id"), "live artifact")
            query = f"projectId={quote(project_id, safe='')}"
            detail = client.get_json(
                f"/api/live-artifacts/{quote(artifact_id, safe='')}?{query}"
            )
            artifact_records.append(
                {
                    "project_id": project_id,
                    "summary": stable_value(artifact),
                    "detail": stable_value(detail),
                    "template_sha256": sha256(
                        client.get_bytes(
                            "/api/live-artifacts/"
                            f"{quote(artifact_id, safe='')}/preview?{query}&variant=template"
                        )
                    ).hexdigest(),
                    "rendered_sha256": sha256(
                        client.get_bytes(
                            "/api/live-artifacts/"
                            f"{quote(artifact_id, safe='')}/preview?{query}&variant=rendered-source"
                        )
                    ).hexdigest(),
                }
            )

    systems_payload = client.get_json("/api/design-systems")
    systems = object_list(systems_payload, "designSystems")
    system_records: list[dict[str, Any]] = []
    for system in sorted(systems, key=lambda item: str(item.get("id") or "")):
        record: dict[str, Any] = {"summary": stable_value(system)}
        if system.get("source") != "built-in":
            system_id = identifier(system.get("id"), "design system")
            record["detail"] = stable_value(
                client.get_json(f"/api/design-systems/{quote(system_id, safe='')}")
            )
            record["files"] = design_system_files(client, system_id)
        system_records.append(record)
    settings = stable_value(client.get_json("/api/app-config"))
    active_runs = object_list(client.get_json("/api/runs"), "runs")
    run_references.extend(stable_run(run) for run in active_runs)
    return {
        "projects": category_digest(project_records),
        "conversations": category_digest(conversation_records),
        "ordered_messages": category_digest(message_records),
        "design_systems": category_digest(system_records),
        "project_files": category_digest(file_records),
        "artifacts": category_digest(artifact_records),
        "settings": category_digest([settings]),
        "run_references": category_digest(
            sorted(run_references, key=lambda item: json.dumps(item, sort_keys=True))
        ),
    }
