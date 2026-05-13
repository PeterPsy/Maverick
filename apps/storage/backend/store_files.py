"""Explicit Storage store facade."""

from __future__ import annotations

from store_files_content import delete_file_payload
from store_files_paths import (
    MAX_PREVIEW_BYTES,
    MAX_READ_BYTES,
    catalog_files_payload,
    file_record,
    list_files,
    list_folders,
    read_file_payload,
    reference_from_payload,
    resolve_storage_file,
    storage_root_for_role,
    write_file_payload,
)
from store_files_records import (
    create_folder_payload,
    delete_folder_payload,
    file_info_payload,
    move_file_payload,
    preview_table_payload,
    preview_text_payload,
    read_folder_payload,
    rename_file_payload,
    update_markdown_file_payload,
    upload_file_payload,
)
from store_files_view import (
    clear_custom_view_payload,
    load_state,
    seed_state,
    set_custom_view_payload,
    set_view_filter_payload,
)


__all__ = [
    "MAX_PREVIEW_BYTES",
    "MAX_READ_BYTES",
    "catalog_files_payload",
    "clear_custom_view_payload",
    "create_folder_payload",
    "delete_file_payload",
    "delete_folder_payload",
    "file_info_payload",
    "file_record",
    "list_files",
    "list_folders",
    "load_state",
    "move_file_payload",
    "preview_table_payload",
    "preview_text_payload",
    "read_file_payload",
    "read_folder_payload",
    "reference_from_payload",
    "rename_file_payload",
    "resolve_storage_file",
    "seed_state",
    "set_custom_view_payload",
    "set_view_filter_payload",
    "storage_root_for_role",
    "update_markdown_file_payload",
    "upload_file_payload",
    "write_file_payload",
]
