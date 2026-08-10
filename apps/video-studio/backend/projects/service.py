"""Single service layer shared by backend, CLI, and MCP surfaces."""

from __future__ import annotations

from .service_core import ProjectServiceCore
from .service_editing import ProjectEditingMixin
from .service_lifecycle import ProjectLifecycleMixin


class ProjectService(ProjectEditingMixin, ProjectLifecycleMixin, ProjectServiceCore):
    """Persistent Project IR and revision-engine application service."""
