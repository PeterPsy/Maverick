# Website Studio

Website Studio is a workspace-local Maverick app for importing, indexing, editing, previewing, diffing, approving, and maintaining company website projects inside the `default` workspace.

This first implementation is Phase 1 of the specification in `storage/generated/website-studio-app-spec.md`. It is a real working app, not only a scaffold.

## Source State

- App id: `website-studio`
- Distribution: `workspace_local`
- Source access: `editable`
- Source root: `workspaces/default/apps/website-studio`
- Workspace data root: `workspaces/default/data/website-studio`
- Primary data: `data/website-studio/app.sqlite` and `data/website-studio/sites`

## Implemented Surfaces

- Frontend workspace app mounted from `frontend/dist`
- Backend action surface at `backend/app_backend.py`
- MCP tools for site list/create/status, ZIP import, Git import, sitemap, search, read/write/apply patch, diff, static preview, publish request, publish blocking, rollback, active context, page context, references, and view state
- CLI command `website-studio`, using the same action names as the backend
- Skill template `website-ops`
- Base-shell sidebar widgets:
  - `website-studio-sitemap-sidebar`
  - `website-studio-sidebar-footer`
- Install, migrate, and health-check hooks

## Phase 1 Behavior

Website Studio supports multiple site records. Each site owns a working source tree under `data/website-studio/sites/<site_id>/source`. ZIP import validates archive members in a staging directory before replacing a source tree, rejects traversal, symlinks, OS executables, sensitive source files, excessive file counts, and size-limit violations, classifies the source as `full_source`, `static_export`, or `partial_source`, records the Storage artifact reference when provided, then indexes static pages, routes, and assets into the sitemap payload. Git import clones a public GitHub HTTPS repository or an app-local repository path into staging with prompt/credential helpers disabled, removes `.git` metadata for Phase 1, validates the imported source tree, classifies it, then indexes the working source.

The app exposes path-safe file reads and writes. Writes and patches require `expected_hash`; new file writes use `expected_hash=new`; stale writes are rejected instead of silently overwriting concurrent edits. Diff compares the current working tree against the active revision snapshot. Static preview renders the selected HTML route into an opaque-origin frontend iframe through sanitized `srcDoc` with a restrictive preview CSP. Phase 1 preview inlines bounded local CSS and static media assets as data URLs; it still does not execute imported JavaScript or arbitrary build commands.

Publishing is intentionally guarded. The app can create a publish request, but `website_publish` always returns a blocked status until Website Studio can validate approval ids through an official approval surface. Rollback is also guarded: `website_rollback` requires `approval_id` and `confirm=true` before replacing the selected working source tree. External GitHub, CMS, commerce, deployment, and managed-hosting writeback are not declared in this contract because they are not implemented in Phase 1.

## Frontend Layout

The central workspace frame is reserved for the selected website only. It does not show the editor, diff, preview, or publish controls; those operations are handled through agent-facing MCP/CLI/backend surfaces.

When no site exists, or when the user clicks `New website` in the sidebar footer, the central frame shows only two centered actions:

- `Drop ZIP`
- `Connect Git`

The base-shell sidebar widget owns site navigation. It shows search first, then the site selector, then the sitemap for the selected site. The sidebar footer action is named `New website`.

## Security Notes

- Website paths are normalized and constrained to the selected site source tree.
- ZIP import rejects absolute paths, `..`, ignored system files, excessive file counts, and excessive expanded size.
- Git import rejects inline credentials, only allows public GitHub HTTPS URLs or local repository paths inside the Website Studio data root, and runs Git with credential prompts/helpers disabled; remote credentials must be handled by future Vault/Core Secrets integration.
- Build/preview currently supports static HTML only; arbitrary dependency installs and executable build commands are not enabled.
- Secrets are not requested or delivered by the Phase 1 contract.
- Storage, Vault, Memory, Chat, and App Store composition must happen through official app/core surfaces.

## Verification

Useful checks:

```bash
python3 -m unittest discover -s apps/website-studio/tests -p 'test_*.py'
maverick app website-studio frontend build --json
maverick core cli run core.app-sdk.validate --app-id website-studio --json
maverick core cli run core.app-sdk.register-local --app-id website-studio --json
maverick core cli run core.app-sdk.install-local --app-id website-studio --json
maverick core cli run core.app-sdk.status --app-id website-studio --json
maverick app website-studio cli list --json
maverick app website-studio mcp list --json
```
