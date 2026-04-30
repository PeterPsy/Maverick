---
name: gallery-ops
description: "Use the Gallery app to inspect workspace uploaded files and generated artifacts through official Maverick app surfaces."
---

# Gallery Ops

Use Gallery when the user needs to inspect files under the active workspace storage roots.

Gallery derives its inventory from:

- `storage/uploaded/`
- `storage/generated/`

Prefer official Gallery MCP, CLI, or backend actions instead of walking these folders directly when operating inside Maverick.

Common actions:

- `catalog`: list uploaded and generated files and folders with metadata.
- `create_folder`: create a folder inside `storage/uploaded/` or `storage/generated/` after Gallery path validation.
- `upload_file`: upload base64 file content into an existing folder under `storage/uploaded/` or `storage/generated/` without overwriting an existing file.
- `move_file`: move a file into a folder or back to the storage root while keeping it inside its current storage role.
- `view_filter`: read the shared Gallery UI filter without scanning workspace storage.
- `read_file`: read a specific file by `role` and `relative_path` for preview or download workflows.
- `write_file` / `file.content.write`: create or overwrite a file by `role` and `relative_path` or `workspace_relative_path`, with UTF-8 `content` or `content_base64`.
- `preview_text`: extract a text preview for text, Markdown, DOCX, PPTX, and XLSX files.
- `preview_table`: extract structured sheet rows for CSV and spreadsheet files so Gallery can render a table preview.
- `update_markdown_file`: replace the UTF-8 contents of a validated `.md` file in workspace storage.
- `set_view_filter`: update the shared Gallery UI filter with `query`, `role`, and `kind` so the frontend can show the filtered view.
- `set_custom_view`: update the shared Gallery UI with a curated file set using `title`, `file_ids`, and/or `workspace_relative_paths`.
- `clear_custom_view`: return Gallery to normal search mode.
- `file_info`: resolve metadata for a file by `role`/`relative_path` or `workspace_relative_path`.
- `rename_file`: rename a file inside its current storage directory.
- `delete_file`: delete a file from the active workspace storage root after Gallery path validation.
