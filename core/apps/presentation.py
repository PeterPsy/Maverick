"""Presentation helpers for app contracts."""

from __future__ import annotations

from core.apps.models import AppContractDescriptor, AppFrontendRole


def app_frontend_role(contract: AppContractDescriptor) -> AppFrontendRole:
    """Return the user-facing frontend role declared by one app contract."""
    return contract.presentation.frontend_role


def app_frontend_is_launchable(contract: AppContractDescriptor) -> bool:
    """Return whether the app has a workspace frontend that users may open."""
    return contract.entrypoints.frontend is not None and contract.presentation.frontend_role == "workspace"


def app_has_supporting_frontend(contract: AppContractDescriptor) -> bool:
    """Return whether the app ships frontend assets that are not an app view."""
    return contract.entrypoints.frontend is not None and contract.presentation.frontend_role == "supporting"
