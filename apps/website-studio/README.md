# Website Studio

Website Studio is a workspace-local Maverick app for importing, indexing, editing, previewing, diffing, approving, and maintaining company website projects inside the `default` workspace.

This implementation covers Phases 1, 2, and the Website Studio-owned portion of Phase 3 from `storage/generated/website-studio-app-spec.md`. It is a real working app, not only a scaffold.

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
- MCP tools for site list/create/status/archive/restore/rename/duplicate/active selection, environment setup, publish target setup, ZIP import, Git import/connection setup, sitemap, search, read/write/apply patch, diff, build validation, change listing, static preview, publish request, approval recording, approved publish, approved rollback, active context, page context, references, and view state
- CLI command `website-studio`, using the same action names as the backend
- Skill template `website-ops`
- Base-shell sidebar widgets:
  - `website-studio-sitemap-sidebar`
  - `website-studio-sidebar-footer`
- Install, migrate, and health-check hooks

## Phase 1, 2, And 3 Behavior

Website Studio supports multiple site records. Each site owns a working source tree under `data/website-studio/sites/<site_id>/source`. Sites can be archived, restored, renamed, duplicated, and selected as the active workspace site without deleting their source or revision history. The active site is persisted in Website Studio view state so the sidebar, main app, and agent context surfaces agree on the selected site; archived sites cannot be selected as active. ZIP import validates archive members in a staging directory before replacing a source tree, rejects traversal, symlinks, OS executables, sensitive source files, excessive file counts, and ZIP upload size-limit violations, normalizes common single-folder export roots, classifies the source as `full_source`, `static_export`, or `partial_source`, records the Storage artifact reference when provided, then indexes static pages, sitemap XML routes, simple redirect routes, SEO metadata, and assets into the sitemap payload. Git import clones a public GitHub HTTPS repository or an app-local repository path into staging with prompt/credential helpers disabled, removes `.git` metadata for Phase 1, rejects symlinks, executable files, sensitive source files, excessive file counts, and bounded source-tree size-limit violations, classifies the imported source tree, then indexes the working source. ZIP and Git imports also return a deterministic `source_profile` with source shape, static preview support, framework hints such as Vite/Astro/Next/Gatsby, and package-manager hints from lockfiles; this detection never installs dependencies or runs imported code.

`website_git_connection_prepare` records a GitHub `owner/repo`, base branch, the fine-grained-token auth mode, and the selected Vault/Core Secrets logical name without receiving raw secret values. It returns redaction-safe `vault_requirements` so Vault can grant `github-token`. `website_git_connection_activate` can explicitly mark a prepared connection as grant-backed when a grant reference is provided with `confirm_no_raw_secret=true`; runtime Core Secrets delivery during import also marks the connection grant-backed after a successful private clone. Raw GitHub tokens are never accepted by the app frontend, CLI, MCP, logs, or summaries. For private GitHub imports, Website Studio uses the Vault-delivered `github-token` only inside the backend Git process through `GIT_ASKPASS`, so the token is not placed in the clone URL or command-line arguments. During approved publish, GitHub-backed sites use the same Vault-delivered token in backend memory only to push changed files to a Maverick branch and open or reuse a pull request.

The app exposes path-safe file reads and writes. Writes and patches require `expected_hash`; new file writes use `expected_hash=new`; source tree mutations are serialized per site so stale writes are rejected instead of silently overwriting concurrent edits. Diff compares the current working tree against the active revision snapshot. Reference payloads include `app_page` and `/app/website-studio/...` deep links for implemented site, page, route, asset, revision, and publish-request entities. Static preview renders the selected HTML route into an opaque-origin frontend iframe through sanitized `srcDoc` with a restrictive preview CSP. Phase 1 preview inlines bounded local CSS and static media assets, including root-relative `/assets/...` references, as data URLs; it still does not execute imported JavaScript or arbitrary build commands, and preview reads do not emit `maverick.app.data-changed` events.

Publishing now uses explicit Website Studio approval events. A publish request requires at least one working-tree diff and a passing deterministic static build validation. `website_approval_record` creates one scoped approval for `publish` or `rollback`; approvals are single-use and must match the selected site, action, and target id. `website_publish` consumes a publish approval, snapshots the working tree as a published revision, marks the publish request and changeset published, and records a deployment. `website_rollback` consumes a rollback approval, restores the selected revision into the working source tree, records a new rollback revision, and records a rollback deployment.

`website_publish_target_configure` can bind a site environment to a managed static publish target. Approved managed-static publish copies the selected working source into an immutable deployment artifact under `data/website-studio/sites/<site_id>/deployments/<artifact_id>/public`, records a redaction-safe `maverick-managed-static` source reference, and marks the deployment mode as `maverick_managed_static`. This implements Website Studio's Phase 3 orchestration boundary: artifact selection, publish request, deployment records, and rollback intent. Generic platform hosting concerns such as custom domains, certificates, CDN/cache policy, and public production binding are still explicitly recorded as `pending_generic_surface` until core exposes a reusable hosting surface.

GitHub-backed sites with an activated grant receive a redaction-safe `github_pull_request` deployment source reference containing the target base branch, Maverick working branch, commit sha, and pull-request URL unless the environment is explicitly configured for `managed_static`. If a GitHub source is configured for Git PR publishing but the grant or runtime secret delivery is missing, publish is blocked before consuming approval. The app still does not perform private Git clone through Vault, deploy to external hosting providers, or run arbitrary build commands. CMS, commerce, external deployment writeback, custom domains, CDN, and certificate automation remain undeclared because they are not implemented.

`website_list_changes` exposes bounded change state for agents: working diff summaries, changesets, publish requests, approval events, build validation records, deployments, and revision metadata for a selected site. It is read-only and does not push, deploy externally, or write back to third-party systems.

## Frontend Layout

The central workspace frame is reserved for the selected website only. It does not show the editor, diff, preview, or publish controls; those operations are handled through agent-facing MCP/CLI/backend surfaces.

When no site exists, or when the user clicks `New website` in the sidebar footer, the central frame shows only two centered actions:

- `Drop ZIP`
- `Connect Git`

`Drop ZIP` supports both file-picker selection and direct drag-and-drop. ZIP bytes are persisted through the resolved Storage provider before Website Studio imports the working copy and stores a Storage artifact reference on the site. `Connect Git` prepares a redaction-safe GitHub connection record and Vault grant requirements; private repo clone/push/PR execution remains a later Phase 2 step.

The base-shell sidebar widget owns site navigation. It shows search first, then the site selector, then the selected site's indexed pages, non-page routes such as redirects or sitemap-only routes, and assets with compact status badges. Page, route, and asset clicks use the shell open-app contract with `pages/<id>`, `routes/<id>`, and `assets/<id>` app pages. The sidebar footer action is named `New website`.

## Security Notes

- Website paths are normalized and constrained to the selected site source tree.
- ZIP import rejects absolute paths, `..`, ignored system files, excessive file counts, and excessive expanded size.
- Git import rejects inline credentials, allows GitHub HTTPS URLs or local repository paths inside the Website Studio data root, and runs Git with credential prompts/helpers disabled unless a prepared and activated GitHub connection receives its token through Core Secrets for private repository clone.
- GitHub connection preparation and activation store only repository metadata, selected auth mode, secret logical names, and redaction-safe grant references; raw GitHub tokens must stay in Vault/Core Secrets and are never accepted by the frontend.
- Build/preview currently supports static HTML validation only; arbitrary dependency installs and executable build commands are not enabled.
- Publish and rollback approvals are explicit, scoped, single-use app records. They are not a substitute for future platform role checks; public production binding remains blocked until generic approval/governance and platform hosting surfaces exist.
- The contract declares a required `file.content.write` Storage provider for user-uploaded ZIP artifact persistence; Storage, Vault, Memory, Chat, and App Store composition must happen through official app/core surfaces.

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
