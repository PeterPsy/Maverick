"""Build Docs Studio pages from workspace-local and server app README files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "app"


def _read_contract(app_root: Path) -> dict[str, Any]:
    path = app_root / "app_contract.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _contract_json(contract: dict[str, Any]) -> str:
    if not contract:
        return "{}"
    return json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=True)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _md(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("\n", " ").replace("|", "\\|")


def _bullet_list(values: list[Any]) -> str:
    if not values:
        return "_None declared._"
    return "\n".join(f"- `{_md(value)}`" for value in values)


def _details(summary: str, body: str) -> str:
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>"


def _surface_count(contract: dict[str, Any], capabilities: dict[str, Any]) -> int:
    entrypoints = _as_dict(contract.get("entrypoints"))
    enabled_entrypoints = sum(1 for name in ("frontend", "backend", "cli", "mcp", "skills_root") if entrypoints.get(name))
    return len(_as_list(capabilities.get("views"))) + len(_as_list(capabilities.get("view_surfaces"))) + enabled_entrypoints


def _entrypoints_section(contract: dict[str, Any]) -> str:
    entrypoints = _as_dict(contract.get("entrypoints"))
    if not entrypoints:
        return "_None declared._"
    rows = []
    for name, value in sorted(entrypoints.items()):
        if isinstance(value, dict):
            value = ", ".join(f"{key}: {item}" for key, item in sorted(value.items()))
        rows.append(f"| `{_md(name)}` | `{_md(value)}` |")
    return "| Entrypoint | Target |\n| --- | --- |\n" + "\n".join(rows)


def _mcp_section(capabilities: dict[str, Any]) -> str:
    return _bullet_list(_as_list(capabilities.get("mcp_tools")))


def _cli_section(capabilities: dict[str, Any]) -> str:
    return _bullet_list(_as_list(capabilities.get("cli_commands")))


def _surfaces_section(contract: dict[str, Any], capabilities: dict[str, Any]) -> str:
    rows = []
    for view in _as_list(capabilities.get("views")):
        rows.append(f"| View | `{_md(view)}` | Declared in `capabilities.views`. |")
    for surface in _as_list(capabilities.get("view_surfaces")):
        if not isinstance(surface, dict):
            continue
        actions = ", ".join(f"`{_md(action.get('action'))}`" for action in _as_list(surface.get("state_actions")) if isinstance(action, dict))
        rows.append(
            f"| View surface | `{_md(surface.get('view_id'))}` | "
            f"{_md(surface.get('display_name'))}; actions: {actions or 'none'}. |"
        )
    entrypoints = _as_dict(contract.get("entrypoints"))
    for name in ("frontend", "backend", "cli", "mcp", "skills_root"):
        target = entrypoints.get(name)
        if target:
            rows.append(f"| Entrypoint surface | `{name}` | `{_md(target)}` |")
    if not rows:
        return "_None declared._"
    return "| Type | Id | Notes |\n| --- | --- | --- |\n" + "\n".join(rows)


def _widgets_section(contract: dict[str, Any]) -> str:
    widgets = _as_list(contract.get("widgets"))
    if not widgets:
        return "_None declared._"
    rows = []
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        frontend = _as_dict(widget.get("frontend"))
        actions = _as_dict(widget.get("actions"))
        enabled_actions = ", ".join(f"`{key}`" for key, enabled in sorted(actions.items()) if enabled) or "none"
        rows.append(
            f"| `{_md(widget.get('widget_id'))}` | `{_md(widget.get('host'))}` | "
            f"`{_md(frontend.get('mount'))}` | {enabled_actions} |"
        )
    return "| Widget | Host | Mount | Actions |\n| --- | --- | --- | --- |\n" + "\n".join(rows)


def _reference_entities_section(capabilities: dict[str, Any]) -> str:
    entities = _as_list(capabilities.get("reference_entities"))
    if not entities:
        return "_None declared._"
    rows = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        abilities = [
            name
            for name in ("searchable", "resolvable", "summarizable", "deep_link_supported")
            if entity.get(name)
        ]
        rows.append(
            f"| `{_md(entity.get('entity_type'))}` | {_md(entity.get('display_name'))} | "
            f"{', '.join(abilities) or 'none'} |"
        )
    return "| Entity type | Display name | Capabilities |\n| --- | --- | --- |\n" + "\n".join(rows)


def _data_events_section(capabilities: dict[str, Any]) -> str:
    events = _as_list(capabilities.get("data_events"))
    if not events:
        return "_None declared._"
    rows = []
    for event in events:
        if isinstance(event, dict):
            rows.append(f"| `{_md(event.get('resource'))}` | {_md(event.get('description'))} |")
        else:
            rows.append(f"| `{_md(event)}` |  |")
    return "| Resource | Description |\n| --- | --- |\n" + "\n".join(rows)


def _provides_requires_section(contract: dict[str, Any]) -> str:
    rows = []
    for label, entries in (("Provides", _as_list(contract.get("provides"))), ("Requires", _as_list(contract.get("requires")))):
        for entry in entries:
            if isinstance(entry, dict):
                surfaces = ", ".join(f"`{_md(surface)}`" for surface in _as_list(entry.get("surfaces")))
                rows.append(
                    f"| {label} | `{_md(entry.get('interface'))}` | "
                    f"`{_md(entry.get('version'))}` | {surfaces or 'none'} | {_md(entry.get('description'))} |"
                )
            else:
                rows.append(f"| {label} | `{_md(entry)}` |  |  |  |")
    if not rows:
        return "_None declared._"
    return "| Direction | Interface | Version | Surfaces | Description |\n| --- | --- | --- | --- | --- |\n" + "\n".join(rows)


def _lifecycle_section(contract: dict[str, Any]) -> str:
    lifecycle = _as_dict(contract.get("lifecycle"))
    if not lifecycle:
        return "_None declared._"
    enabled = [name for name, value in sorted(lifecycle.items()) if value]
    disabled = [name for name, value in sorted(lifecycle.items()) if not value]
    return (
        "### Enabled\n\n"
        f"{_bullet_list(enabled)}\n\n"
        "### Disabled\n\n"
        f"{_bullet_list(disabled)}"
    )


def _storage_section(contract: dict[str, Any]) -> str:
    storage = _as_dict(contract.get("storage"))
    if not storage:
        return "_None declared._"
    paths = _as_list(storage.get("primary_paths"))
    rows = [
        f"| Kind | `{_md(storage.get('storage_kind'))}` |",
        f"| Schema version | `{_md(storage.get('data_schema_version'))}` |",
        f"| Export | `{bool(storage.get('supports_export'))}` |",
        f"| Import | `{bool(storage.get('supports_import'))}` |",
        f"| Migrations | `{bool(storage.get('supports_migrations'))}` |",
    ]
    path_list = _bullet_list(paths)
    return "| Field | Value |\n| --- | --- |\n" + "\n".join(rows) + f"\n\n### Primary paths\n\n{path_list}"


def _policy_section(contract: dict[str, Any]) -> str:
    distribution = _as_dict(contract.get("distribution"))
    compatibility = _as_dict(contract.get("compatibility"))
    visibility = _as_dict(contract.get("visibility"))
    rows = [
        f"| Distribution mode | `{_md(distribution.get('mode'))}` |",
        f"| Source access | `{_md(distribution.get('source_access'))}` |",
        f"| Workspace modes | `{_md(', '.join(_as_list(compatibility.get('workspace_modes'))))}` |",
        f"| Platform roles | `{_md(', '.join(_as_list(visibility.get('platform_roles'))))}` |",
    ]
    return "| Field | Value |\n| --- | --- |\n" + "\n".join(rows)


def _contract_overview(contract: dict[str, Any]) -> str:
    capabilities = _as_dict(contract.get("capabilities"))
    lifecycle = _as_dict(contract.get("lifecycle"))
    storage = _as_dict(contract.get("storage"))
    policy_count = sum(1 for key in ("distribution", "compatibility", "visibility") if isinstance(contract.get(key), dict))
    sections = [
        _details(f"Entrypoints ({len(_as_dict(contract.get('entrypoints')))})", _entrypoints_section(contract)),
        _details(f"CLI commands ({len(_as_list(capabilities.get('cli_commands')))})", _cli_section(capabilities)),
        _details(f"MCP tools ({len(_as_list(capabilities.get('mcp_tools')))})", _mcp_section(capabilities)),
        _details(f"Surfaces and views ({_surface_count(contract, capabilities)})", _surfaces_section(contract, capabilities)),
        _details(f"Widgets ({len(_as_list(contract.get('widgets')))})", _widgets_section(contract)),
        _details(f"Reference entities ({len(_as_list(capabilities.get('reference_entities')))})", _reference_entities_section(capabilities)),
        _details(f"Skills ({len(_as_list(capabilities.get('skills')))})", _bullet_list(_as_list(capabilities.get("skills")))),
        _details(f"Data events ({len(_as_list(capabilities.get('data_events')))})", _data_events_section(capabilities)),
        _details(
            f"Provides and requires ({len(_as_list(contract.get('provides'))) + len(_as_list(contract.get('requires')))})",
            _provides_requires_section(contract),
        ),
        _details(f"Lifecycle ({len(lifecycle)})", _lifecycle_section(contract)),
        _details(f"Storage ({len(_as_list(storage.get('primary_paths')))})", _storage_section(contract)),
        _details(f"Distribution, compatibility, and visibility ({policy_count})", _policy_section(contract)),
    ]
    return "\n\n".join(sections)


def _read_readme(app_root: Path, replacements: list[tuple[str, str]]) -> str:
    path = app_root / "README.md"
    if not path.exists():
        return "_No README.md is present for this app source._"
    readme = path.read_text(encoding="utf-8").strip()
    for original, replacement in replacements:
        readme = readme.replace(original, replacement)
    return readme


def _source_summary(source: dict[str, str]) -> str:
    return (
        f"| {source['kind']} | `{source['relative_path']}` | "
        f"`{source['distribution_mode']}` | `{source['source_access']}` |"
    )


def _source_label(sources: list[dict[str, str]]) -> str:
    return " + ".join(source["kind"] for source in sources)


def _source_paths(sources: list[dict[str, str]]) -> str:
    return ", ".join(f"{source['kind']} `{source['relative_path']}`" for source in sources)


def _readme_blocks(sources: list[dict[str, str]]) -> list[str]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        grouped.setdefault(source["readme"], []).append(source)
    blocks = []
    for readme, grouped_sources in grouped.items():
        blocks.append(
            f"## README ({_source_label(grouped_sources)})\n\n"
            f"> Sources: {_source_paths(grouped_sources)}\n\n"
            f"{readme}"
        )
    return blocks


def _discover_app_sources(root: Path, kind: str, replacements: list[tuple[str, str]]) -> list[dict[str, str]]:
    apps: list[dict[str, str]] = []
    if not root.exists():
        return apps
    for app_root in sorted(item for item in root.iterdir() if item.is_dir()):
        contract = _read_contract(app_root)
        app_id = str(contract.get("app_id") or app_root.name)
        distribution = contract.get("distribution") if isinstance(contract.get("distribution"), dict) else {}
        apps.append({
            "app_id": app_id,
            "name": str(contract.get("name") or app_id.replace("-", " ").title()),
            "description": str(contract.get("description") or "Workspace app."),
            "version": str(contract.get("version") or ""),
            "distribution_mode": str(distribution.get("mode") or ""),
            "source_access": str(distribution.get("source_access") or ""),
            "kind": kind,
            "relative_path": str(app_root.relative_to(root.parent)),
            "contract_overview": _contract_overview(contract),
            "contract_json": _contract_json(contract),
            "readme": _read_readme(app_root, replacements),
        })
    return apps


def build_apps_section(workspace_root: Path | None = None) -> dict[str, object]:
    """Return one Docs Studio section containing README pages for known apps."""
    if workspace_root is None:
        workspace_root = Path(__file__).resolve().parents[3]
    install_root = workspace_root.parents[1]
    replacements = [
        (str(workspace_root) + "/", "<workspace>/"),
        (str(install_root) + "/", "<maverick-root>/"),
        (str(Path.home()) + "/", "<home>/"),
    ]
    sources = [
        *_discover_app_sources(workspace_root / "apps", "workspace", replacements),
        *_discover_app_sources(install_root / "apps", "server", replacements),
    ]

    grouped: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        grouped.setdefault(source["app_id"], []).append(source)

    pages = []
    for app_id in sorted(grouped):
        app_sources = grouped[app_id]
        primary = app_sources[0]
        source_rows = "\n".join(_source_summary(source) for source in app_sources)
        source_blocks = [*_readme_blocks(app_sources)]
        for source in app_sources:
            source_blocks.append(
                f"## Contract overview ({source['kind']})\n\n"
                f"{source['contract_overview']}\n\n"
                f"## Raw contract ({source['kind']})\n\n"
                f"<details>\n"
                f"<summary>View app_contract.json from {source['relative_path']}</summary>\n\n"
                f"```json\n{source['contract_json']}\n```\n\n"
                f"</details>"
            )
        body = (
            f"# {primary['name']}\n\n"
            f"{primary['description']}\n\n"
            "## Source inventory\n\n"
            "| Source | Path | Distribution | Access |\n"
            "| --- | --- | --- | --- |\n"
            f"{source_rows}\n\n"
            f"{chr(10).join(source_blocks)}"
        )
        pages.append({
            "id": f"app-{_slug(app_id)}",
            "title": primary["name"],
            "icon": "app",
            "summary": primary["description"],
            "body": body,
            "source_app_id": app_id,
            "updated_at": "",
        })
    return {
        "id": "apps",
        "title": "Apps",
        "pages": pages,
    }
