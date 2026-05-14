"""Remote App Store catalog payload normalization."""

from __future__ import annotations


def normalize_catalog_item(item: dict[str, object]) -> dict[str, object]:
    normalized = _normalize_catalog_presentation_payload(item)
    raw_versions = item.get("versions")
    if isinstance(raw_versions, list):
        normalized["versions"] = [
            _normalize_catalog_presentation_payload(version, parent=normalized)
            for version in raw_versions
            if isinstance(version, dict)
        ]
    return normalized


def _normalize_catalog_presentation_payload(
    item: dict[str, object],
    *,
    parent: dict[str, object] | None = None,
) -> dict[str, object]:
    normalized = dict(item)
    if parent is not None:
        inherited_fields = (
            "app_id",
            "name",
            "description",
            "publisher",
            "presentation",
            "frontend_role",
            "frontend_launchable",
        )
        for field in inherited_fields:
            if not normalized.get(field) and parent.get(field):
                normalized[field] = parent[field]
    role = _catalog_frontend_role(normalized)
    normalized["presentation"] = _normalized_presentation(normalized.get("presentation"), role=role)
    normalized["frontend_role"] = role
    normalized["frontend_launchable"] = _catalog_frontend_launchable(normalized, role=role)
    normalized["surfaces"] = _catalog_surface_labels(normalized, role=role)
    return normalized


def _normalized_presentation(value: object, *, role: str) -> dict[str, object]:
    if isinstance(value, dict):
        return {**value, "frontend_role": role}
    return {"frontend_role": role}


def _catalog_frontend_role(item: dict[str, object]) -> str:
    explicit = _catalog_role_value(item.get("frontend_role"))
    if explicit:
        return explicit
    presentation = item.get("presentation")
    if isinstance(presentation, dict):
        explicit = _catalog_role_value(presentation.get("frontend_role"))
        if explicit:
            return explicit
    surfaces = _catalog_string_list(item.get("surfaces"))
    if "supporting_frontend" in surfaces:
        return "supporting"
    if "frontend" in surfaces:
        return "workspace"
    if item.get("frontend_launchable") is True:
        return "workspace"
    entrypoints = item.get("entrypoints")
    if isinstance(entrypoints, dict) and entrypoints.get("frontend"):
        return "workspace"
    return "none"


def _catalog_role_value(value: object) -> str | None:
    role = str(value or "").strip()
    return role if role in {"workspace", "supporting", "none"} else None


def _catalog_frontend_launchable(item: dict[str, object], *, role: str) -> bool:
    if role != "workspace":
        return False
    value = item.get("frontend_launchable")
    if isinstance(value, bool):
        return value
    return True


def _catalog_surface_labels(item: dict[str, object], *, role: str) -> list[str]:
    surfaces = _unique_strings(_catalog_string_list(item.get("surfaces")))
    if role == "workspace":
        surfaces = _with_surface(surfaces, "frontend")
        surfaces = [surface for surface in surfaces if surface != "supporting_frontend"]
    elif role == "supporting":
        surfaces = _with_surface(surfaces, "supporting_frontend")
        surfaces = [surface for surface in surfaces if surface != "frontend"]
    else:
        surfaces = [surface for surface in surfaces if surface not in {"frontend", "supporting_frontend"}]

    entrypoints = item.get("entrypoints")
    if isinstance(entrypoints, dict):
        if entrypoints.get("backend"):
            surfaces = _with_surface(surfaces, "backend")
        if entrypoints.get("mcp"):
            surfaces = _with_surface(surfaces, "mcp")
        if entrypoints.get("cli"):
            surfaces = _with_surface(surfaces, "cli")
        if entrypoints.get("skills_root"):
            surfaces = _with_surface(surfaces, "skills")

    capabilities = item.get("capabilities")
    if isinstance(capabilities, dict):
        if _catalog_string_list(capabilities.get("mcp_tools")):
            surfaces = _with_surface(surfaces, "mcp")
        if _catalog_string_list(capabilities.get("cli_commands")):
            surfaces = _with_surface(surfaces, "cli")
        if _catalog_string_list(capabilities.get("skills")):
            surfaces = _with_surface(surfaces, "skills")

    widgets = item.get("widgets")
    if isinstance(widgets, list) and widgets:
        surfaces = _with_surface(surfaces, "widgets")
    return surfaces


def _catalog_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _unique_strings(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    return unique_values


def _with_surface(surfaces: list[str], surface: str) -> list[str]:
    if surface not in surfaces:
        return [*surfaces, surface]
    return surfaces
