# Storage

Workspace file storage for uploaded files and generated artifacts.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `storage-ops` skill, persisted storage view-state actions, the base-shell `storage-sidebar` and `storage-sidebar-footer` widgets, and the `file-preview` chat widget.
- `file` is the primary reference entity. App-owned state lives under `data/storage/state.json`; the derived file inventory lives under `data/storage/files.json`.
- Storage is one of the repository reference apps for file-centric references and embedded widget surfaces.
- File records expose stable `file_<uuid>` ids that survive Storage-managed rename and move operations. `path_id` keeps the legacy `uploaded:<path>` or `generated:<path>` value as navigation metadata.
- Catalog results default to newest workspace storage artifacts first, using filesystem modification time with path order as the stable tiebreaker.
- Catalog supports server-side `query`, `role`, `kind`, `folder_path`, `file_ids`, `workspace_relative_paths`, `offset`, and `limit` parameters. `folder_path: ""` means the selected storage root's direct files, while an omitted `folder_path` leaves folder scoping disabled. `references.search` and `references.resolve` use the inventory instead of recursively scanning storage on each call.
- Catalog returns files and folders from one inventory refresh snapshot. Normal catalog calls reconcile known files plus changed directories so out-of-band workspace files appear without requiring frontend callers to pass `sync: true`.
- Storage-managed upload, write, Markdown update, folder create/delete, rename, move, and delete actions hold the workspace Storage write lock while they validate paths, touch bytes, enforce quota, and update `files.json`.
- Storage hides upload implementation folders such as UUID buckets and presents those uploaded files at the visible Uploaded root.
- The Uploaded and Generated storage roots render as top-level folder cards in the Storage browser.
- Folder cards expose details, ZIP download, and delete actions; storage root folders can be downloaded but not deleted.
- Destructive file and folder deletes use an app-rendered confirmation dialog instead of browser modal APIs so the mounted Storage iframe works under the shell sandbox policy.
- The Storage browser requests one bounded page of the current folder or search view at a time. When no search query is active, the backend filters direct child files by `folder_path`; a non-empty `Search in Storage` query searches folders and files across Uploaded and Generated storage at once while file-type filters still refine matching files.
- Direct navigation to a file resolves the target by stable id or workspace-relative path, exits custom/search scoping, reloads the file's containing folder, and then merges the resolved file into the visible page if it is outside the first page.
- The breadcrumb heading shows direct folder and file counts plus the current folder's recursive size in MB.
- Users can create folders inside `storage/uploaded/` and `storage/generated/` from the sidebar's selected folder, and drag files into folders. File moves stay inside the file's current storage role.
- Users can upload a local file from the sidebar into the selected Uploaded or Generated folder; Storage validates the target folder and refuses silent overwrites.
- Users can also drag local files onto any part of the Storage app to upload them into the currently displayed folder, with animated feedback for ready, uploading, success, and blocked states.
- The frontend supports animated list and card layouts so users can switch between compact file rows and visual file cards.
- Storage contributes its file-type filter rail, navigation tree, and folder actions through base shell sidebar widget slots instead of rendering a separate in-app sidebar; the rail shows only file types currently present in workspace storage.
- The app-level `Search in Storage` control searches files and folders globally across workspace storage; the sidebar navigation tree mirrors that shared view-state query instead of exposing a separate folder search.
- CSV and XLSX previews expose structured rows to the frontend so the preview modal can render spreadsheet-like tables instead of plain delimited text.
- Text, Markdown, CSV, and XLSX previews are bounded by server-side byte, row, column, and archive budgets before extraction.
- Markdown previews render common Markdown structure, including headings, lists, code blocks, links, blockquotes, and pipe tables, in both the Storage app and the file-preview widget instead of showing raw Markdown text.
- Markdown files can be edited from the Storage preview modal with a source editor and live rendered preview, copied in full to the clipboard, then saved back to the same validated workspace storage path.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-root apps/storage --app-id storage --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id storage --workspace default --json
```

`validate --app-root apps/storage` is the authoritative source-tree check for this installation-level app. `status --app-id storage` is a partial SDK diagnostic aimed at workspace-local app projects; for Storage it may report `source_exists: false` or a failed binding when the install-level source is absent or unhealthy. Use `maverick apps list --json` to verify that Storage is actually mounted in the active workspace.

`register-local`, `install-local`, and `package` operate on workspace-local app projects under `workspaces/<workspace_id>/apps/<app_id>/`; they are not the correct flow for this installation-level Storage app source.
