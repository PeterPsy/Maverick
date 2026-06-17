---
name: storage-ops
description: "Use the Storage app to inspect workspace uploaded files, generated artifacts, and connected Google Drive files through official Maverick app surfaces."
---

# Storage Ops

Use Storage when the user needs to inspect files under the active workspace storage roots or connected remote storage providers such as Google Drive.

Storage derives its inventory from:

- `storage/uploaded/`
- `storage/generated/`

Prefer official Storage MCP, CLI, or backend actions instead of walking these folders directly when operating inside Maverick.

For Google Drive, Storage is the gateway. Do not ask Memory for Google tokens, do not treat Drive as a local filesystem, and do not use `workspace_relative_path` for Drive files.

Common actions:

- `catalog`: list uploaded and generated files and folders with metadata.
- `create_folder`: create a folder inside `storage/uploaded/` or `storage/generated/` after Storage path validation.
- `upload_file`: upload base64 file content into an existing folder under `storage/uploaded/` or `storage/generated/` without overwriting an existing file. Use this only for inline payloads up to 25 MiB decoded.
- CLI-only `upload_local_file`: upload a trusted local source path into Storage through chunked local upload sessions without putting large base64 payloads on the shell command line.
- `local_upload_session.start` / `local_upload_session.chunk` / `local_upload_session.status` / `local_upload_session.cancel`: upload local workspace files above 25 MiB and up to 500 MiB through 8 MiB decoded chunks. Start the session with role, folder, filename, content type, and total size; send chunks at the acknowledged `expected_offset`; call status to recover after ambiguous failures.
- `move_file`: move a file into a folder or back to the storage root while keeping it inside its current storage role.
- `move_folder`: move a non-root folder into another folder or back to the storage root while keeping it inside its current storage role; Storage rejects path escapes, collisions, and moves into the same folder subtree.
- `view_filter`: read the shared Storage UI filter without scanning workspace storage.
- `read_file`: read a specific file by `role` and `relative_path` for bounded inline binary/download workflows. Use Storage media URLs for browser downloads of large local files.
- `read_text` / `file.text.read`: extract document text from text, Markdown, DOCX, PPTX, and XLSX files without the preview character cap; use `offset` and `max_chars` only when you intentionally want a window.
- `write_file` / `file.content.write`: create or overwrite a file by `role` and `relative_path` or `workspace_relative_path`, with UTF-8 `content` or `content_base64`.
- `preview_text`: extract a bounded text preview for UI-style preview workflows, not for complete document reading.
- `preview_table`: extract structured sheet rows for CSV and spreadsheet files so Storage can render a table preview.
- `update_markdown_file`: replace the UTF-8 contents of a validated `.md` file in workspace storage.
- `set_view_filter`: update the shared Storage UI filter with `query`, `role`, and `kind` so the frontend can show the filtered view.
- `set_custom_view`: update the shared Storage UI with a curated file set using `title`, `file_ids`, and/or `workspace_relative_paths`.
- `clear_custom_view`: return Storage to normal search mode.
- `file_info`: resolve metadata for a file by `role`/`relative_path` or `workspace_relative_path`.
- `file.reconcile`: refresh Storage inventory after external workspace writes, or refresh one known Drive file record.
- `rename_file`: rename a file inside its current storage directory.
- `delete_file`: delete a file from the active workspace storage root after Storage path validation.
- `download_folder` / `read_folder`: read a validated folder as a bounded inline ZIP archive. Browser folder downloads stream through `/api/apps/<app_id>/media?media_kind=folder` so large archives are served as files instead of JSON/base64 payloads.
- `delete_folder`: delete a non-root folder from the active workspace storage root after Storage path validation.

For binary files already produced on the local filesystem by a trusted CLI workflow, prefer the CLI-only local upload wrapper:

```bash
maverick app storage cli run storage --arguments-json '{
  "action": "upload_local_file",
  "source_path": "/tmp/output.pdf",
  "workspace_relative_path": "storage/generated/pdf-edits/output.pdf",
  "content_type": "application/pdf",
  "mode": "create"
}'
```

Do not expose `source_path` through MCP, frontend, or browser-facing flows.

## Google Drive Agent Workflow

When a user asks about Drive content, keep the loop selective:

1. Search Memory first if the user is asking for knowledge already seen.
2. If fresh Drive evidence is needed, list or search Drive through Storage:

```bash
maverick app storage mcp call storage_drive_search --json --connection-id <drive_connection_id> --query "<search terms>" --limit 10
maverick app storage mcp call storage_drive_list_children --json --connection-id <drive_connection_id> --parent-drive-file-id <drive_folder_id>
```

3. For one selected candidate file, prepare Memory ingestion:

```bash
maverick app storage mcp call storage_drive_index --json --connection-id <drive_connection_id> --drive-file-id <drive_file_id>
```

4. Pass the returned `memory_source`, `preview_text`, `preview_truncated`, and `source_version` unchanged to Memory `memory_ingest_storage_source`.
5. After Memory ingest succeeds, acknowledge the handoff in Storage:

```bash
maverick app storage mcp call storage_drive_mark_indexed --json --stable-storage-file-id <stable_storage_file_id> --source-version <source_version> --memory-node-id <node_id> --memory-external-ref-id <external_ref_id> --memory-source-version-id <source_version_id>
```

Only call `drive_mark_indexed` after Memory returns success. Without that acknowledgement, later `drive_sync` cannot reliably emit Memory staleness for the file.

When `drive_sync` returns `memory_staleness`, pass each item to Memory `memory_apply_storage_staleness`; Storage does not write Memory data directly.

For Drive playback, use `storage_file_localize`, `storage_file_localize_status`, `storage_file_localize_retry`, and `storage_file_localize_cancel` instead of treating Drive as a mounted filesystem. Storage does not expose local host paths through CLI or MCP; trusted backend consumers must use the governed `file.local.path` dependency backend integration.
