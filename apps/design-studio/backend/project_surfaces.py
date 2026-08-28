"""Display-safe project/reference projections over public OpenDesign APIs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from opendesign_client import OpenDesignNotFound, validated_identifier


class ProjectSurfaces:
    """Expose OpenDesign-owned projects without mirroring their semantic state."""

    def __init__(self, client: Any, app_id: str) -> None:
        self.client = client
        self.app_id = app_id or "design-studio"

    def list_projects(self) -> list[dict[str, Any]]:
        return [sanitize_project(project) for project in self.client.list_projects()]

    def reference_manifest(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "schema_version": "1",
            "entity_types": [{
                "entity_type": "design_project",
                "display_name": "OpenDesign project",
                "id_stability": "stable",
                "searchable": True,
                "resolvable": True,
                "summarizable": True,
                "deep_link_supported": True,
            }],
        }

    def reference_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip().casefold()
        if len(query) > 200:
            raise ValueError("query exceeds 200 characters.")
        limit = arguments.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        projects = self.list_projects()
        results = [
            self.reference_item(project)
            for project in projects
            if not query
            or query in project["name"].casefold()
            or query in project["id"].casefold()
        ]
        return {"results": results[:limit]}

    def reference_resolve(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project_id = validated_identifier(
            arguments.get("entity_id") or arguments.get("project_id"),
            label="OpenDesign project id",
        )
        try:
            project = sanitize_project(self.client.get_project(project_id))
        except OpenDesignNotFound:
            return {
                "exists": False,
                "app_id": self.app_id,
                "entity_type": "design_project",
                "entity_id": project_id,
            }
        if project["id"] != project_id:
            raise ValueError("OpenDesign project identity mismatch.")
        return {"exists": True, **self.reference_item(project)}

    def reference_summarize(self, arguments: dict[str, Any]) -> dict[str, Any]:
        resolved = self.reference_resolve(arguments)
        if not resolved.get("exists"):
            return {"summary": "", "safe_fields": {}, "source_updated_at": ""}
        return {
            "summary": resolved["summary"],
            "safe_fields": {
                "name": resolved["title"],
                "status": resolved.get("status", ""),
            },
            "source_updated_at": resolved.get("updated_at", ""),
        }

    def reference_item(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = validated_identifier(project.get("id"), label="OpenDesign project id")
        name = str(project.get("name") or project_id)[:200]
        status = str(project.get("status") or "")
        summary = f"OpenDesign project {name}"
        if status:
            summary += f" ({status})"
        app = quote(self.app_id, safe="")
        native = quote(project_id, safe="")
        return {
            "app_id": self.app_id,
            "entity_type": "design_project",
            "entity_id": project_id,
            "title": name,
            "summary": summary,
            "status": status,
            "updated_at": project.get("updated_at", ""),
            "deep_link": f"/app/{app}/projects/{native}",
            "od_project_id": project_id,
        }


def sanitize_project(project: dict[str, Any]) -> dict[str, Any]:
    """Retain only display-safe scalar native project metadata."""
    project_id = validated_identifier(project.get("id"), label="OpenDesign project id")
    status = project.get("status")
    status_value = status.get("value") if isinstance(status, dict) else status
    return {
        "id": project_id,
        "name": str(project.get("name") or project_id).strip().replace("\x00", "")[:200],
        "status": str(status_value or "").strip()[:80],
        "created_at": _safe_timestamp(project.get("createdAt", project.get("created_at"))),
        "updated_at": _safe_timestamp(project.get("updatedAt", project.get("updated_at"))),
    }


def _safe_timestamp(value: object) -> str | int | float:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return value
    return str(value or "").strip()[:64]
