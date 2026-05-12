# Gallery

Workspace file gallery for uploaded files and generated artifacts.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `gallery-ops` skill, persisted gallery view-state actions, the base-shell `gallery-sidebar` widget, and the `file-preview` chat widget.
- `file` is the primary reference entity and app-owned state lives under `data/gallery/state.json`.
- Gallery is one of the repository reference apps for file-centric references and embedded widget surfaces.
- Catalog results default to newest workspace storage artifacts first, using filesystem modification time with path order as the stable tiebreaker.
- Catalog results include folders from workspace storage so the frontend can present uploaded and generated artifacts as a navigable folder view.
- Gallery hides upload implementation folders such as UUID buckets and presents those uploaded files at the visible Uploaded root.
- Users can create folders inside `storage/uploaded/` and `storage/generated/`, drag files into folders, and move files back out through folder breadcrumbs. File moves stay inside the file's current storage role.
- Users can upload a local file into the currently displayed folder after choosing either the Uploaded or Generated storage role; Gallery validates the target folder and refuses silent overwrites.
- Users can also drag local files onto any part of the Gallery app to upload them into the currently displayed folder, with animated feedback for ready, uploading, success, and blocked states.
- The frontend supports card and details layouts so users can switch between visual browsing and dense file navigation.
- Gallery contributes its file search/navigation sidebar through the base shell widget slot instead of rendering a separate in-app sidebar.
- CSV and XLSX previews expose structured rows to the frontend so the preview modal can render spreadsheet-like tables instead of plain delimited text.
- Markdown previews render common Markdown structure, including headings, lists, code blocks, links, blockquotes, and pipe tables, in both the Gallery app and the file-preview widget instead of showing raw Markdown text.
- Markdown files can be edited from the Gallery preview modal with a source editor and live rendered preview, copied in full to the clipboard, then saved back to the same validated workspace storage path.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id gallery --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id gallery --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id gallery --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id gallery --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id gallery --workspace default --json
```
