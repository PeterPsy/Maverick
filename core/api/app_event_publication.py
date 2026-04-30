"""Guarded publication for app-owned live invalidation events."""

from __future__ import annotations

import logging
from typing import Any, Iterable


LOGGER = logging.getLogger(__name__)
ALLOWED_APP_EVENT_TYPES = {"maverick.app.data-changed"}


def publish_declared_app_events(
    app_event_bus,
    result: dict[str, Any],
    *,
    workspace_id: str,
    app_id: str,
    declared_resources: Iterable[str],
    remove_from_result: bool = False,
) -> None:
    """Publish only contract-declared app events, stamped with core-owned identity."""
    if remove_from_result:
        events = result.pop("app_events", [])
    else:
        events = result.get("app_events", [])
    if app_event_bus is None:
        return
    if not isinstance(events, list):
        return
    allowed_resources = {resource for resource in declared_resources if resource}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "maverick.app.data-changed").strip()
        resource = str(event.get("resource") or "").strip()
        if event_type not in ALLOWED_APP_EVENT_TYPES:
            LOGGER.warning("Ignoring undeclared app event type `%s` from `%s`.", event_type, app_id)
            continue
        if resource not in allowed_resources:
            LOGGER.warning("Ignoring undeclared app event resource `%s` from `%s`.", resource, app_id)
            continue
        app_event_bus.publish(
            {
                "type": event_type,
                "workspace_id": workspace_id,
                "owner_app_id": app_id,
                "resource": resource,
            }
        )


def declared_data_event_resources(data_events: Iterable[Any]) -> list[str]:
    """Return resource ids from parsed app contract data-event declarations."""
    return [event.resource for event in data_events]
