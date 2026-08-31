"""Fail-closed browser file-cache descriptor projection for Storage."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlencode

from drive_oauth import (
    GOOGLE_DRIVE_CLIENT_ID_SECRET,
    GOOGLE_DRIVE_CLIENT_SECRET_SECRET,
    GOOGLE_DRIVE_REFRESH_TOKEN_SECRET,
)
from errors import StorageValidationError
from storage_mime import normalize_content_type
from storage_provider_model import GOOGLE_DRIVE_PROVIDER


FILE_CACHE_DESCRIPTOR_SCHEMA = "maverick.storage-file-cache-descriptor.v1"
LOCAL_PERSISTENCE_POLICY_REVISION = "maverick.local-persistence-policy.v2"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def stable_source_version(file_record: dict[str, Any]) -> str:
    """Return only a provider revision or content digest suitable for cache identity."""
    if str(file_record.get("provider") or "local") == GOOGLE_DRIVE_PROVIDER:
        source_version = str(file_record.get("source_version") or "").strip()
        if source_version:
            return source_version
        legacy_version = str(file_record.get("etag_or_version") or "").strip()
        modified_at = str(file_record.get("modified_at") or "").strip()
        return legacy_version if legacy_version and legacy_version != modified_at else ""
    digest = str(file_record.get("sha256") or "").strip().lower()
    return f"sha256:{digest}" if SHA256_PATTERN.fullmatch(digest) else ""


def file_cache_descriptor_payload(
    *,
    file_record: dict[str, Any],
    requested_source_version: str,
    app_id: str = "storage",
) -> dict[str, Any]:
    """Project trusted identity while keeping unclassified bytes network-only."""
    file_id = str(file_record.get("file_id") or file_record.get("id") or "").strip()
    source_version = stable_source_version(file_record)
    requested = str(requested_source_version or "").strip()
    if not file_id:
        raise StorageValidationError("Storage file cache identity is missing.", operation="file.cache_descriptor")
    if not source_version:
        return _descriptor(
            file_record=file_record,
            file_id=file_id,
            source_version="",
            reason_code="unstable_version",
            app_id=app_id,
        )
    if not requested:
        raise StorageValidationError(
            "Storage file cache source_version is required.",
            operation="file.cache_descriptor",
            expected_fields=["stable_storage_file_id", "source_version"],
        )
    if requested != source_version:
        raise StorageValidationError(
            "Storage file cache source_version is stale; refresh the file record and retry.",
            operation="file.cache_descriptor",
            expected_fields=["stable_storage_file_id", "source_version"],
        )
    return _descriptor(
        file_record=file_record,
        file_id=file_id,
        source_version=source_version,
        reason_code="unclassified",
        app_id=app_id,
    )


def _descriptor(
    *,
    file_record: dict[str, Any],
    file_id: str,
    source_version: str,
    reason_code: str,
    app_id: str,
) -> dict[str, Any]:
    digest = str(file_record.get("sha256") or "").strip().lower()
    expected_sha256 = digest if SHA256_PATTERN.fullmatch(digest) else ""
    return {
        "schema": FILE_CACHE_DESCRIPTOR_SCHEMA,
        "eligible": False,
        "reason_code": reason_code,
        "policy": {
            "policy_revision": LOCAL_PERSISTENCE_POLICY_REVISION,
            "data_class": "unclassified",
            "provenance": "attachment",
            "cache_approved": False,
            "privacy_approved": False,
            "regulated_allowlisted": False,
        },
        "file": {
            "file_id": file_id,
            "source_version": source_version,
            "size_bytes": max(0, int(file_record.get("size_bytes") or 0)),
            "content_type": normalize_content_type(file_record.get("content_type"), file_name=file_record.get("name")),
            "expected_sha256": expected_sha256,
            "media_url": _media_url(
                app_id=app_id,
                file_record=file_record,
                file_id=file_id,
                source_version=source_version,
            ),
        },
    }


def _media_url(*, app_id: str, file_record: dict[str, Any], file_id: str, source_version: str) -> str:
    query: dict[str, str] = {
        "stable_storage_file_id": file_id,
        "source_version": source_version,
        "download": "1",
        "_pwa_file_cache": "1",
        "_app_secret_request": json.dumps(
            _drive_secret_request(file_record)
            if str(file_record.get("provider") or "local") == GOOGLE_DRIVE_PROVIDER
            else {"logical_names": [], "required": False},
            separators=(",", ":"),
            sort_keys=True,
        ),
    }
    if str(file_record.get("provider") or "local") == GOOGLE_DRIVE_PROVIDER:
        query["connection_id"] = str(file_record.get("connection_id") or "")
        query["drive_file_id"] = str(file_record.get("drive_file_id") or "")
    return f"/api/apps/{quote(app_id or 'storage', safe='')}/media?{urlencode(query)}"


def _drive_secret_request(file_record: dict[str, Any]) -> dict[str, Any]:
    selectors: list[dict[str, Any]] = [{
        "logical_names": [GOOGLE_DRIVE_CLIENT_ID_SECRET, GOOGLE_DRIVE_CLIENT_SECRET_SECRET],
    }]
    connection_id = str(file_record.get("connection_id") or "").strip()
    if connection_id:
        selectors.append({
            "logical_names": [GOOGLE_DRIVE_REFRESH_TOKEN_SECRET],
            "resource_id": connection_id,
            "resource_type": "drive_connection",
        })
    return {"required": True, "selectors": selectors}
