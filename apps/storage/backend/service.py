"""Storage action router; heavy capabilities are loaded only by their own routes."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from operations_manifest import STORAGE_ACTION_ALIASES
from service_protocol import DRIVE_SECRET_ACTIONS, app_events_for_action, app_events_for_result

__all__ = ['handle_action', 'app_events_for_action', 'app_events_for_result', 'secret_lookup_for_drive_action',
    'prepare_media_response_body', 'stream_prepared_media_response_body', 'stream_media_response_body']

READ_ACTIONS = {
    'catalog', 'catalog.summary', 'directory.children', 'file.catalog.list', 'operations.manifest',
    'references.manifest', 'references.resolve', 'references.search', 'references.summarize', 'view_filter',
}


def handle_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any], **options):
    requested = str(body.get('action') or 'catalog')
    action = STORAGE_ACTION_ALIASES.get(requested, requested)
    if action in READ_ACTIONS:
        from service_reads import handle_read_action
        return handle_read_action(data_root, uploaded_root, generated_root, body, action)
    from service_actions import handle_action as execute
    return execute(data_root, uploaded_root, generated_root, body, **options)


def secret_lookup_for_drive_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any]):
    requested = str(body.get('action') or '')
    if STORAGE_ACTION_ALIASES.get(requested, requested) not in DRIVE_SECRET_ACTIONS:
        return {'requires_secrets': False}
    from service_actions import secret_lookup_for_drive_action as lookup
    return lookup(data_root, uploaded_root, generated_root, body)


def prepare_media_response_body(*args, **kwargs):
    from service_actions import prepare_media_response_body as prepare
    return prepare(*args, **kwargs)


def stream_prepared_media_response_body(*args, **kwargs):
    from service_actions import stream_prepared_media_response_body as stream
    return stream(*args, **kwargs)


def stream_media_response_body(*args, **kwargs):
    from service_actions import stream_media_response_body as stream
    return stream(*args, **kwargs)
