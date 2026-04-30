"""Storage section parsing for app contracts."""

from __future__ import annotations

from pathlib import Path

from core.apps.errors import AppContractValidationError
from core.apps.models import AppStorageDeclaration, AppStorageIndices
from core.apps.contract_validation import _expect_bool, _expect_mapping, _expect_string, _expect_string_list, _reject_unexpected_fields


def parse_storage_section(payload: dict[str, object], *, app_id: str) -> AppStorageDeclaration:
    _reject_unexpected_fields(
        payload,
        {
            "storage_kind",
            "data_schema_version",
            "primary_paths",
            "indices",
            "supports_export",
            "supports_import",
            "supports_migrations",
        },
        label="storage",
    )
    primary_paths = _expect_string_list(payload, "primary_paths")
    for index, primary_path in enumerate(primary_paths):
        if Path(primary_path).is_absolute():
            raise AppContractValidationError("`storage.primary_paths` entries must be relative.")
        expected_prefix = f"data/{app_id}/"
        if not primary_path.startswith(expected_prefix):
            raise AppContractValidationError(
                f"`storage.primary_paths[{index}]` must stay under `{expected_prefix}`."
            )
    indices_payload = payload.get("indices")
    indices = None
    if indices_payload is not None:
        indices_mapping = _expect_mapping(indices_payload, label="storage.indices")
        _reject_unexpected_fields(indices_mapping, {"kind"}, label="storage.indices")
        indices = AppStorageIndices(kind=_expect_string(indices_mapping, "kind"))
    return AppStorageDeclaration(
        storage_kind=_expect_string(payload, "storage_kind"),
        data_schema_version=_expect_string(payload, "data_schema_version"),
        primary_paths=primary_paths,
        indices=indices,
        supports_export=_expect_bool(payload, "supports_export", default=False),
        supports_import=_expect_bool(payload, "supports_import", default=False),
        supports_migrations=_expect_bool(payload, "supports_migrations", default=False),
    )
