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

- `catalog`: list uploaded and generated files with metadata.
- `view_filter`: read the shared Gallery UI filter without scanning workspace storage.
- `read_file`: read a specific file by `role` and `relative_path` for preview or download workflows.
- `preview_text`: extract a text preview for text, Markdown, DOCX, PPTX, and XLSX files.
- `set_view_filter`: update the shared Gallery UI filter with `query`, `role`, and `kind` so the frontend can show the filtered view.
- `set_custom_view`: update the shared Gallery UI with a curated file set using `title`, `file_ids`, and/or `workspace_relative_paths`.
- `clear_custom_view`: return Gallery to normal search mode.
- `file_info`: resolve metadata for a file by `role`/`relative_path` or `workspace_relative_path`.
- `rename_file`: rename a file inside its current storage directory.
- `delete_file`: delete a file from the active workspace storage root after Gallery path validation.
