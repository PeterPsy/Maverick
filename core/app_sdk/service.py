"""Official Maverick app SDK service."""

from __future__ import annotations

from pathlib import Path

from core.app_sdk.errors import AppSdkPathError, AppSdkValidationError
from core.app_sdk.models import (
    AppSdkCreateRequest,
    AppSdkCreateResult,
    AppSdkStatusResult,
    AppSdkValidationIssue,
    AppSdkValidationResult,
)
from core.app_sdk.templates import render_template_files
from core.app_sdk.validation import validate_app_source_completeness
from core.apps.contracts import APP_ID_PATTERN, parse_app_contract_file
from core.apps.errors import AppHostingError
from core.apps.paths import installed_app_root, workspace_apps_root
from core.apps.service import install_workspace_local_app, register_workspace_local_app_project_from_contract
from core.apps.store import AppStore


def create_app_source(request: AppSdkCreateRequest, *, start_path: Path | None = None) -> AppSdkCreateResult:
    """Generate one Maverick app source tree from an SDK template."""
    _validate_app_id(request.app_id)
    app_root = _target_app_root(request, start_path=start_path)
    if app_root.exists() and any(app_root.iterdir()) and not request.overwrite:
        raise AppSdkPathError(f"App root `{app_root}` already exists. Pass overwrite to replace SDK-owned files.")
    files = render_template_files(request)
    written: list[str] = []
    app_root.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        target = _safe_child(app_root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(str(target))
    validation = validate_app_source(app_root)
    if not validation.valid:
        issue_text = "; ".join(issue.message for issue in validation.issues)
        raise AppSdkValidationError(f"Generated app `{request.app_id}` did not validate: {issue_text}")
    return AppSdkCreateResult(
        app_id=request.app_id,
        template_id=request.template_id,
        target_kind=request.target_kind,
        app_root=str(app_root),
        contract_path=str(app_root / "app_contract.json"),
        files_written=written,
    )


def validate_app_source(app_root: str | Path) -> AppSdkValidationResult:
    """Validate one Maverick app source tree through the canonical contract parser."""
    root = Path(app_root)
    try:
        parsed = parse_app_contract_file(root)
    except AppHostingError as error:
        return AppSdkValidationResult(
            valid=False,
            app_id=None,
            app_root=str(root),
            issues=[AppSdkValidationIssue(field="app_contract.json", message=str(error))],
        )
    issues: list[AppSdkValidationIssue] = []
    if parsed.contract.distribution.mode == "workspace_local" and parsed.contract.distribution.source_access != "editable":
        issues.append(
            AppSdkValidationIssue(
                field="distribution.source_access",
                message="Workspace-local apps must use source_access `editable`.",
            )
        )
    issues.extend(validate_app_source_completeness(root, parsed))
    return AppSdkValidationResult(valid=not issues, app_id=parsed.app_id, app_root=str(root), issues=issues)


def register_local_app(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> dict[str, str]:
    """Register one workspace-local app project through generic app-hosting registration."""
    _validate_app_id(app_id)
    project_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path) / app_id
    _raise_if_invalid(validate_app_source(project_root))
    record = register_workspace_local_app_project_from_contract(
        store,
        workspace_id=workspace_id,
        project_root=str(project_root),
    )
    return {
        "status": "registered",
        "workspace_id": record.workspace_id,
        "app_id": record.app_id,
        "project_id": record.project_id,
        "project_root": record.project_root,
    }


def install_local_app(
    store: AppStore,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
    observability_store=None,
) -> dict[str, str]:
    """Install one registered workspace-local app through generic app-hosting installation."""
    _validate_app_id(app_id)
    project_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path) / app_id
    _raise_if_invalid(validate_app_source(project_root))
    binding = install_workspace_local_app(
        store,
        workspace_id=workspace_id,
        app_id=app_id,
        start_path=start_path,
        observability_store=observability_store,
    )
    return {
        "status": "installed",
        "workspace_id": binding.workspace_id,
        "app_id": binding.app_id,
        "binding_status": binding.status,
        "data_root": binding.data_root,
    }


def app_sdk_status(
    store: AppStore | None,
    *,
    workspace_id: str,
    app_id: str,
    start_path: Path | None = None,
) -> AppSdkStatusResult:
    """Return source, registration, installation, and validation state for one workspace-local app."""
    _validate_app_id(app_id)
    project_root = workspace_apps_root(workspace_id=workspace_id, start_path=start_path) / app_id
    validation = validate_app_source(project_root) if project_root.exists() else None
    registered = False
    installed = False
    binding_status = None
    data_root = None
    if store is not None:
        try:
            store.get_workspace_local_app_project(workspace_id=workspace_id, app_id=app_id)
            registered = True
        except AppHostingError:
            registered = False
        try:
            binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=app_id)
            installed = True
            binding_status = binding.status
            data_root = binding.data_root
        except AppHostingError:
            installed = False
    return AppSdkStatusResult(
        app_id=app_id,
        workspace_id=workspace_id,
        source_exists=project_root.exists(),
        registered=registered,
        installed=installed,
        binding_status=binding_status,
        project_root=str(project_root) if project_root.exists() else None,
        data_root=data_root,
        validation=validation,
    )


def _target_app_root(request: AppSdkCreateRequest, *, start_path: Path | None = None) -> Path:
    if request.target_kind == "workspace_local":
        if not request.workspace_id:
            raise AppSdkPathError("Workspace-local SDK app creation requires a workspace_id.")
        return workspace_apps_root(workspace_id=request.workspace_id, start_path=start_path) / request.app_id
    if request.target_kind == "platform":
        return installed_app_root(app_id=request.app_id, start_path=start_path)
    raise AppSdkPathError(f"Unsupported SDK target kind `{request.target_kind}`.")


def _safe_child(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise AppSdkPathError("SDK template paths must be relative.")
    resolved = (root / candidate).resolve()
    safe_root = root.resolve()
    if resolved != safe_root and safe_root not in resolved.parents:
        raise AppSdkPathError(f"SDK template path `{relative_path}` escapes `{safe_root}`.")
    return resolved


def _validate_app_id(app_id: str) -> None:
    if not APP_ID_PATTERN.fullmatch(app_id):
        raise AppSdkValidationError(f"App id `{app_id}` must use lowercase kebab-case.")


def _raise_if_invalid(validation: AppSdkValidationResult) -> None:
    if validation.valid:
        return
    details = "; ".join(f"{issue.field}: {issue.message}" for issue in validation.issues)
    raise AppSdkValidationError(f"App source `{validation.app_root}` did not pass SDK validation: {details}")
