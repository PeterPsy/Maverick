"""Lightweight repository fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import tempfile
import unittest

from core.apps.contracts import (
    build_app_capabilities,
    build_app_contract,
    build_app_entrypoints,
    build_app_lifecycle,
    build_app_permissions,
    build_app_storage,
    build_parsed_app_contract,
    build_view_surface_declaration,
    build_widget_actions,
    build_widget_declaration,
    build_widget_frontend,
    write_app_contract_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def make_temp_repo_root(test_case: unittest.TestCase, *, include_core: bool = False) -> Path:
    """Create an isolated repo root with mutable workspace storage.

    Source trees that tests only need to read should be linked with
    ``link_repo_child`` or ``link_app_sources`` instead of copied.
    """

    temp_dir = tempfile.TemporaryDirectory()
    test_case.addCleanup(temp_dir.cleanup)
    repo_root = Path(temp_dir.name) / "maverick"
    for name in ("apps", "workspaces", "scripts"):
        (repo_root / name).mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "architecture").mkdir(parents=True, exist_ok=True)
    (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
    if include_core:
        link_repo_child(repo_root, "core")
    else:
        (repo_root / "core").mkdir(parents=True, exist_ok=True)
    return repo_root


def link_repo_child(repo_root: Path, child_name: str) -> None:
    destination = repo_root / child_name
    if destination.exists() or destination.is_symlink():
        return
    _link_or_copy(REPO_ROOT / child_name, destination)


def link_app_sources(repo_root: Path, app_ids: list[str] | None = None, *, skip_runtime_app_sdk_imports: bool = False) -> None:
    source_apps_root = REPO_ROOT / "apps"
    sources = []
    if app_ids is None:
        sources = sorted(path for path in source_apps_root.iterdir() if (path / "app_contract.json").is_file())
    else:
        sources = [source_apps_root / app_id for app_id in app_ids]

    for source_path in sources:
        if not (source_path / "app_contract.json").is_file():
            continue
        if skip_runtime_app_sdk_imports and _runtime_imports_app_sdk(source_path):
            continue
        destination = repo_root / "apps" / source_path.name
        if destination.exists() or destination.is_symlink():
            continue
        _link_or_copy(source_path, destination)


def write_synthetic_platform_app(
    repo_root: Path,
    *,
    app_id: str,
    name: str | None = None,
    frontend: bool = True,
    backend: bool = False,
    cli_commands: list[str] | None = None,
    mcp_tools: list[str] | None = None,
    skills: list[str] | None = None,
    views: list[str] | None = None,
    widget_specs: list[dict[str, object]] | None = None,
    runtime_create_sessions: bool = False,
) -> Path:
    """Write a minimal platform app source for tests that do not need real app hooks."""

    app_root = repo_root / "apps" / app_id
    frontend_mount = "frontend/dist" if frontend else None
    backend_path = "backend/app_backend.py" if backend else None
    skills_root = "skills" if skills else None
    widgets = [
        build_widget_declaration(
            widget_id=str(spec["widget_id"]),
            host=str(spec["host"]),
            content_kinds=[str(item) for item in spec.get("content_kinds", [])],
            frontend=build_widget_frontend(mount=str(spec["mount"])),
            actions=build_widget_actions(backend=bool(spec.get("backend", False))),
        )
        for spec in widget_specs or []
    ]
    parsed = build_parsed_app_contract(
        app_id=app_id,
        name=name or app_id.replace("-", " ").title(),
        version="1.0.0",
        description=f"Synthetic {app_id} app for integration tests.",
        publisher="test",
        contract=build_app_contract(
            permissions=build_app_permissions(runtime_create_sessions=runtime_create_sessions),
            capabilities=build_app_capabilities(
                mcp_tools=mcp_tools or [],
                cli_commands=cli_commands or [],
                skills=skills or [],
                views=views or [],
                view_surfaces=[
                    build_view_surface_declaration(view_id=view_id, display_name=view_id.replace("-", " ").title())
                    for view_id in views or []
                ],
            ),
            lifecycle=build_app_lifecycle(
                install=False,
                upgrade=False,
                uninstall=False,
                health_check=False,
            ),
            entrypoints=build_app_entrypoints(
                backend=backend_path,
                frontend=frontend_mount,
                skills_root=skills_root,
            ),
            storage=build_app_storage(
                data_schema_version="1",
                primary_paths=[f"data/{app_id}/state.json"],
                supports_export=False,
                supports_import=False,
            ),
            widgets=widgets,
        ),
    )
    write_app_contract_file(app_root, parsed)
    if frontend:
        dist_root = app_root / "frontend" / "dist"
        (dist_root / "assets").mkdir(parents=True, exist_ok=True)
        asset_name = f"app-{app_id}-fixture01.js"
        (dist_root / "assets" / asset_name).write_text(
            (
                f"const syntheticAppId = {app_id!r};\n"
                "window.__maverickSyntheticApps = window.__maverickSyntheticApps || {};\n"
                "window.__maverickSyntheticApps[syntheticAppId] = {\n"
                "  mounted: true,\n"
                "  source: 'tests.support.repo.write_synthetic_platform_app'\n"
                "};\n"
            ),
            encoding="utf-8",
        )
        (dist_root / "index.html").write_text(
            f'<div id="root">{name or app_id}</div><script src="/apps/{app_id}/assets/{asset_name}"></script>',
            encoding="utf-8",
        )
    if backend:
        backend_root = app_root / "backend"
        backend_root.mkdir(parents=True, exist_ok=True)
        (backend_root / "app_backend.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "body = payload.get('body') if isinstance(payload.get('body'), dict) else {}\n"
            "action = body.get('action')\n"
            "if action == 'projects.create':\n"
            "    project = {'project_id': 'project-1', 'name': body.get('name') or 'Project'}\n"
            "    result = {'status_code': 201, 'json': {'project': project, 'projects': [project]}}\n"
            "elif action == 'projects.list':\n"
            "    result = {'status_code': 200, 'json': {'projects': []}}\n"
            "else:\n"
            "    result = {'status_code': 200, 'json': {'ok': True}}\n"
            "json.dump(result, sys.stdout)\n",
            encoding="utf-8",
        )
    for skill_id in skills or []:
        skill_root = app_root / "skills" / skill_id
        skill_root.mkdir(parents=True, exist_ok=True)
        (skill_root / "SKILL.md").write_text(f"---\nname: {skill_id}\n---\nSynthetic skill.\n", encoding="utf-8")
    for spec in widget_specs or []:
        mount = str(spec["mount"])
        widget_root = app_root / mount
        widget_root.mkdir(parents=True, exist_ok=True)
        (widget_root / "index.html").write_text(f"<div>{spec['widget_id']}</div>", encoding="utf-8")
    return app_root


def _runtime_imports_app_sdk(source_path: Path) -> bool:
    for path in source_path.glob("**/*.py"):
        if "tests" in path.relative_to(source_path).parts:
            continue
        if "core.app_sdk" in path.read_text(encoding="utf-8"):
            return True
    return False


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.symlink(source, destination, target_is_directory=source.is_dir())
    except OSError:
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
