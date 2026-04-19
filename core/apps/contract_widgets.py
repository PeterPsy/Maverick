"""Widget contract parsing helpers."""

from __future__ import annotations

from pathlib import Path

from core.apps.contract_validation import (
    _expect_bool,
    _expect_content_kind_list,
    _expect_mapping,
    _expect_relative_mount_path,
    _expect_slug,
    _expect_string,
)
from core.apps.errors import AppContractValidationError
from core.apps.models import AppEntrypoints, WidgetActionDeclaration, WidgetDeclaration, WidgetFrontendDeclaration


def parse_widget_declarations(source_root: Path, root: dict, entrypoints: AppEntrypoints) -> list[WidgetDeclaration]:
    """Parse and validate app-owned embeddable widget declarations."""
    widgets_payload = root.get("widgets", [])
    if not isinstance(widgets_payload, list):
        raise AppContractValidationError("`widgets` must be a list.")
    widgets: list[WidgetDeclaration] = []
    seen_widget_ids: set[str] = set()
    for index, widget_payload in enumerate(widgets_payload):
        widget = _expect_mapping(widget_payload, label=f"widgets[{index}]")
        widget_id = _expect_slug(widget, "widget_id")
        if widget_id in seen_widget_ids:
            raise AppContractValidationError(f"Duplicate widget_id `{widget_id}`.")
        seen_widget_ids.add(widget_id)
        frontend_payload = _expect_mapping(widget.get("frontend", {}), label=f"widgets[{index}].frontend")
        actions_payload = _expect_mapping(widget.get("actions", {}), label=f"widgets[{index}].actions")
        frontend_kind = _expect_string(frontend_payload, "kind")
        if frontend_kind != "iframe":
            raise AppContractValidationError("`widgets[].frontend.kind` currently supports only `iframe`.")
        frontend = WidgetFrontendDeclaration(
            kind=frontend_kind,
            mount=_expect_relative_mount_path(
                source_root,
                _expect_string(frontend_payload, "mount"),
                label=f"widgets[{index}].frontend.mount",
            ),
            spa_fallback=_expect_bool(frontend_payload, "spa_fallback", default=True),
        )
        actions = WidgetActionDeclaration(
            backend=_expect_bool(actions_payload, "backend", default=False),
            mcp=_expect_bool(actions_payload, "mcp", default=False),
            cli=_expect_bool(actions_payload, "cli", default=False),
        )
        if actions.backend and entrypoints.backend is None:
            raise AppContractValidationError("Widget backend actions require `entrypoints.backend`.")
        if actions.mcp and entrypoints.mcp is None:
            raise AppContractValidationError("Widget MCP actions require `entrypoints.mcp`.")
        if actions.cli and entrypoints.cli is None:
            raise AppContractValidationError("Widget CLI actions require `entrypoints.cli`.")
        widgets.append(
            WidgetDeclaration(
                widget_id=widget_id,
                host=_expect_slug(widget, "host"),
                content_kinds=_expect_content_kind_list(widget, "content_kinds"),
                frontend=frontend,
                actions=actions,
            )
        )
    return widgets
