"""Data models for the official Maverick app SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AppSdkTemplateId = Literal[
    "minimal",
    "frontend-backend",
    "agent-tool",
    "data-app",
    "widget",
    "react-vite",
    "entity-sqlite",
]
AppSdkTargetKind = Literal["workspace_local", "platform"]


@dataclass(frozen=True)
class AppSdkCreateRequest:
    """Input for generating one Maverick app source tree."""

    app_id: str
    template_id: AppSdkTemplateId
    target_kind: AppSdkTargetKind
    workspace_id: str | None = None
    name: str | None = None
    description: str | None = None
    publisher: str = "workspace"
    version: str = "0.1.0"
    overwrite: bool = False
    entities: list[str] | None = None


@dataclass(frozen=True)
class AppSdkCreateResult:
    """Result returned after generating an app source tree."""

    app_id: str
    template_id: str
    target_kind: str
    app_root: str
    contract_path: str
    files_written: list[str]


@dataclass(frozen=True)
class AppSdkValidationIssue:
    """One actionable validation finding."""

    field: str
    message: str


@dataclass(frozen=True)
class AppSdkValidationResult:
    """Validation result for one app source tree."""

    valid: bool
    app_id: str | None
    app_root: str
    issues: list[AppSdkValidationIssue]


@dataclass(frozen=True)
class AppSdkStatusResult:
    """Developer-facing state for one app in one workspace."""

    app_id: str
    workspace_id: str
    source_exists: bool
    registered: bool
    installed: bool
    binding_status: str | None
    project_root: str | None
    data_root: str | None
    validation: AppSdkValidationResult | None


@dataclass(frozen=True)
class AppSdkPackageResult:
    """Result returned after packaging one app source tree."""

    app_id: str
    version: str
    app_root: str
    artifact_path: str
    manifest_path: str
    checksum_sha256: str
    files_packaged: list[str]
