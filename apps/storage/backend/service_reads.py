"""Catalog and reference reads without Drive, media, upload or conversion imports."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from service_protocol import (CATALOG_ROLES, CATALOG_KINDS, _optional_nonnegative_int, _optional_positive_int, _bool_value, _catalog_filter_value, _catalog_folder_path, _optional_string_list)
from inventory import catalog_inventory_payload as catalog_files_payload
from operations_manifest import operations_manifest_payload
from reference_entities import REFERENCE_MANIFEST, reference_resolve_payload, reference_search_payload, reference_summarize_payload
from store_files_view import load_state
from storage_provider_model import reject_remote_workspace_relative_path


def handle_read_action(data_root: Path, uploaded_root: Path, generated_root: Path, body: dict[str, Any], action: str):
    reject_remote_workspace_relative_path(provider=body.get('provider'), workspace_relative_path=body.get('workspace_relative_path'), workspace_relative_paths=body.get('workspace_relative_paths'))
    if action == "operations.manifest":
        return 200, operations_manifest_payload()
    if action == 'catalog.summary':
        from inventory_admin import catalog_summary
        summary = catalog_summary(data_root, uploaded_root, generated_root)
        response = {'schema': 'storage.file-catalog.v1', 'state': load_state(data_root),
            'files': [], 'folders': [], 'summary': summary, 'dataset_revision': summary.get('dataset_revision'),
            'available_kinds': summary.get('available_kinds', []),
            'pagination': {'offset': 0, 'limit': 0, 'total': 0, 'has_more': False}}
        return 200, {**response, 'revision': hashlib.sha256(json.dumps(response, sort_keys=True).encode()).hexdigest()}
    if action == 'directory.children':
        from inventory_admin import catalog_directories
        return 200, catalog_directories(data_root, uploaded_root, generated_root,
            role=_catalog_filter_value(body, 'role', {'uploaded', 'generated', 'all'}, 'generated'),
            query=str(body.get('query') or ''),
            parent=str(body.get('folder_path') or '').strip('/'),
            offset=_optional_nonnegative_int(body, 'offset') or 0,
            limit=_optional_positive_int(body, 'limit', maximum=2000) or 100,
            dataset_revision=_optional_nonnegative_int(body, 'dataset_revision'))
    if action in {"catalog", "file.catalog.list"}:
        catalog = catalog_files_payload(
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            sync=_bool_value(body.get("sync")),
            query=str(body.get("query") or ""),
            role=_catalog_filter_value(body, "role", CATALOG_ROLES, "all"),
            kind=_catalog_filter_value(body, "kind", CATALOG_KINDS, "all"),
            offset=_optional_nonnegative_int(body, "offset") or 0,
            limit=_optional_positive_int(body, "limit", maximum=2000),
            sort_by=str(body['sort_by']) if body.get('sort_by') else None,
            sort_direction=str(body.get("sort_direction") or "desc"),
            folder_path=_catalog_folder_path(body),
            file_ids=_optional_string_list(body, "file_ids"),
            workspace_relative_paths=_optional_string_list(body, "workspace_relative_paths"),
            dataset_revision=_optional_nonnegative_int(body, "dataset_revision"),
        )
        if catalog.get('status') == 'catalog_changed':
            return 200, {**catalog, 'schema': 'storage.file-catalog.v1'}
        response = {
            "schema": "storage.file-catalog.v1",
            "state": load_state(data_root),
            "files": catalog["files"],
            "folders": catalog["folders"],
            "pagination": catalog["pagination"],
            "inventory": catalog["inventory"],
            "available_kinds": catalog["available_kinds"],
            **{key: catalog[key] for key in ('dataset_revision', 'summary', 'totals', 'folders_pagination') if key in catalog},
        }
        revision_payload = {
            **response,
            "inventory": {
                "schema_version": str(response["inventory"].get("schema_version") or ""),
            },
        }
        revision = hashlib.sha256(
            json.dumps(revision_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if str(body.get("known_revision") or "").strip() == revision:
            return 200, {
                "schema": "storage.file-catalog.v1",
                "revision": revision,
                "not_modified": True,
            }
        return 200, {**response, "revision": revision, "not_modified": False}
    if action == "view_filter":
        return 200, {"state": load_state(data_root)}
    if action == "references.manifest":
        return 200, REFERENCE_MANIFEST
    if action == "references.search":
        return 200, reference_search_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root, body=body)
    if action == "references.resolve":
        return 200, reference_resolve_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root, body=body)
    if action == "references.summarize":
        return 200, reference_summarize_payload(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root, body=body)
    raise ValueError(f'Not a Storage read action: {action}')
