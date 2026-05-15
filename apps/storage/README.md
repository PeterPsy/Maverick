# Storage

Workspace file storage for uploaded files and generated artifacts.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `storage-ops` skill, persisted storage view-state actions, the base-shell `storage-sidebar` and `storage-sidebar-footer` widgets, and the `file-preview` chat widget.
- `file` and `folder` are reference entities. App-owned state lives under `data/storage/state.json`; the derived file and folder inventory lives under `data/storage/files.json`.
- Storage is one of the repository reference apps for file- and folder-centric references and embedded widget surfaces.
- The Storage view surface currently declares only `file` for standard custom view composition; folder references are searchable, resolvable, summarizable, and deep-linkable, but custom views remain file-only.
- File records expose stable `file_<uuid>` ids that survive Storage-managed rename and move operations. `path_id` keeps the legacy `uploaded:<path>` or `generated:<path>` value as navigation metadata.
- Folder references use path-based percent-encoded ids such as `generated:Client%20Docs/`; they resolve only while that visible folder path exists.
- Catalog results default to newest workspace storage artifacts first, using filesystem modification time with path order as the stable tiebreaker.
- Catalog supports server-side `query`, `role`, `kind`, `folder_path`, `file_ids`, `workspace_relative_paths`, `offset`, and `limit` parameters. `folder_path: ""` means the selected storage root's direct files, while an omitted `folder_path` leaves folder scoping disabled. `references.search` and `references.resolve` use the inventory instead of recursively scanning storage on each call, and expose both workspace files and visible Storage folders to generic `@` reference pickers such as Chat.
- Catalog returns files and folders from one inventory refresh snapshot. Normal catalog calls reconcile known files plus changed directories so out-of-band workspace files appear without requiring frontend callers to pass `sync: true`.
- Storage-managed upload, write, Markdown update, folder create/delete, rename, move, batch move, and delete actions hold the workspace Storage write lock while they validate paths, touch bytes, enforce quota, and update `files.json`.
- Storage hides upload implementation folders such as UUID buckets and presents those uploaded files at the visible Uploaded root.
- The Uploaded and Generated storage roots render as top-level folder cards in the Storage browser.
- Folder cards expose details, ZIP download, drag-to-move, and delete actions; storage root folders can be downloaded and used as move targets but not moved or deleted.
- Destructive file and folder deletes use an app-rendered confirmation dialog instead of browser modal APIs so the mounted Storage iframe works under the shell sandbox policy.
- The Storage browser requests one bounded page of the current folder or search view at a time. When no search query is active, the backend filters direct child files by `folder_path`; a non-empty `Search in Storage` query searches folders and files across Uploaded and Generated storage at once while file-type filters still refine matching files.
- Direct navigation to a file resolves the target by stable id or workspace-relative path, exits custom/search scoping, reloads the file's containing folder, and then merges the resolved file into the visible page if it is outside the first page.
- The breadcrumb heading shows direct folder and file counts plus the current folder's recursive size in MB.
- After server-confirmed upload, rename, Markdown edit, move, create, or delete actions, the frontend patches the loaded catalog snapshot immediately and then revalidates the authoritative catalog in the background. The backend remains the source of truth; the fast visual update is not applied before the server accepts the mutation.
- Users can create folders inside `storage/uploaded/` and `storage/generated/` from the sidebar's selected folder, and drag Storage files or folders into visible folder cards or sidebar tree folders. Moves stay inside the item's current storage role; folder moves reject root folders, path escapes, name collisions, and attempts to move a folder into itself or a child folder.
- Storage drag payloads allow both move and copy operations: Storage folder targets use them for within-role moves, while Chat can read the same file, folder, or selection payloads as copy-style citations in the floating/full composer.
- Long-pressing a visible file or movable folder enters selection mode, showing selection toggles on the current screen. Dragging a selected item moves the selected files and folders together into a visible folder card or sidebar tree folder through one `move_items` backend action under one Storage write lock, or cites the selected files and folders when dropped into Chat, using the same item payload as single-item drags.
- Users can upload a local file from the sidebar into the selected Uploaded or Generated folder; Storage validates the target folder and refuses silent overwrites.
- Users can also drag local files onto any part of the Storage app to upload them into the currently displayed folder, with animated feedback for ready, uploading, success, and blocked states.
- The frontend supports animated list and card layouts so users can switch between compact file rows and visual file cards.
- Storage contributes its file-type filter rail, navigation tree, and folder actions through base shell sidebar widget slots instead of rendering a separate in-app sidebar; the rail shows only file types currently present in workspace storage.
- The sidebar file-type rail forwards the saved `view_filter` through the shell event detail so the mounted Storage app can apply the filter immediately, then refresh the catalog page against that filter.
- The app-level `Search in Storage` control searches files and folders globally across workspace storage; the sidebar navigation tree mirrors that shared view-state query instead of exposing a separate folder search.
- CSV and XLSX previews expose structured rows to the frontend so the preview modal can render spreadsheet-like tables instead of plain delimited text.
- Text, Markdown, CSV, and XLSX previews are bounded by server-side byte, row, column, and archive budgets before extraction.
- Markdown previews render common Markdown structure, including headings, lists, code blocks, links, blockquotes, and pipe tables, in both the Storage app and the file-preview widget instead of showing raw Markdown text.
- The file-preview chat widget renders the file body as one neutral Chat-style document box with a compact clickable title row, keeps the skeleton visible until inline preview content is ready, posts bounded height updates, keeps iframe scrolling hidden, and groups fullscreen/open actions beside the title.
- Markdown files can be edited from the Storage preview modal with a source editor and live rendered preview, copied in full to the clipboard, then saved back to the same validated workspace storage path.
- The Storage preview modal header exposes a fullscreen toggle; it uses the browser Fullscreen API when allowed and falls back to an in-app fullscreen layout when iframe policy blocks native fullscreen. On mobile, the preview modal fills the app viewport below the shell header with borderless chrome, truncates long titles on one row, hides the fullscreen action, fits image previews inside the available box without cropping, and renders content directly below that header.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-root apps/storage --app-id storage --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id storage --workspace default --json
```

`validate --app-root apps/storage` is the authoritative source-tree check for this installation-level app. `status --app-id storage` is a partial SDK diagnostic aimed at workspace-local app projects; for Storage it may report `source_exists: false` or a failed binding when the install-level source is absent or unhealthy. Use `maverick apps list --json` to verify that Storage is actually mounted in the active workspace.

`register-local`, `install-local`, and `package` operate on workspace-local app projects under `workspaces/<workspace_id>/apps/<app_id>/`; they are not the correct flow for this installation-level Storage app source.
