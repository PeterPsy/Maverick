# Website Studio

Website Studio is a workspace-local Maverick app for importing, indexing, editing, previewing, diffing, approving, and maintaining company website projects inside the `default` workspace.

This implementation covers Phases 1, 2, and the Website Studio-owned Phase 3A runtime/governance work from `storage/generated/website-studio-app-spec.md`. It is a real working app, not only a scaffold.

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
- MCP tools for site list/create/status/archive/restore/rename/duplicate/active selection, environment setup, publish target setup, ZIP import, Git import/connection setup, Git source sync, sitemap, search, read/write/apply patch, diff, build validation, change listing, static preview, isolated preview document retrieval, runtime health, publish request, approval recording, approved publish, approved rollback, active context, page context, references, and view state
- CLI command `website-studio`, using the same action names as the backend
- Skill template `website-ops`
- Base-shell sidebar widgets:
  - `website-studio-sitemap-sidebar`
  - `website-studio-sidebar-footer`
- Install, migrate, and health-check hooks

## Phase 1, 2, And 3A Behavior

Website Studio supports multiple site records. Each site owns a working source tree under `data/website-studio/sites/<site_id>/source`. Sites can be archived, restored, renamed, duplicated, and selected as the active workspace site without deleting their source or revision history. The active site is persisted in Website Studio view state so the sidebar, main app, and agent context surfaces agree on the selected site; archived sites cannot be selected as active. ZIP import validates archive members in a staging directory before replacing a source tree, rejects traversal, symlinks, OS executables, sensitive source files, excessive file counts, and ZIP upload size-limit violations, normalizes common single-folder export roots, classifies the source as `full_source`, `static_export`, or `partial_source`, records the Storage artifact reference when provided, then indexes static pages, sitemap XML routes, simple redirect routes, SEO metadata, and assets into the sitemap payload. Git import clones a public GitHub HTTPS repository or an app-local repository path into staging with prompt/credential helpers disabled, removes `.git` metadata for Phase 1, rejects symlinks, executable files, sensitive source files, excessive file counts, and bounded source-tree size-limit violations, classifies the imported source tree, then indexes the working source. ZIP and Git imports also return a deterministic `source_profile` with source shape, static preview support, framework hints such as Vite/Astro/Next/Gatsby, and package-manager hints from lockfiles; this detection never installs dependencies or runs imported code.

`website_git_connection_prepare` records a GitHub `owner/repo`, base branch, the fine-grained-token auth mode, and the selected Vault/Core Secrets logical name without receiving raw secret values. It returns redaction-safe `vault_requirements` so Vault can grant `github-token`. `website_git_connection_activate` can explicitly mark a prepared connection as grant-backed when a grant reference is provided with `confirm_no_raw_secret=true`; runtime Core Secrets delivery during import also marks the connection grant-backed after a successful private clone. Raw GitHub tokens are never accepted by the app frontend, CLI, MCP, logs, or summaries. For private GitHub imports, Website Studio uses the Vault-delivered `github-token` only inside the backend Git process through `GIT_ASKPASS`, so the token is not placed in the clone URL or command-line arguments. During approved publish, GitHub-backed sites use the same Vault-delivered token in backend memory only to push changed files to a Maverick branch and open or reuse a pull request.

The app exposes path-safe file reads and writes. Writes and patches require `expected_hash`; new file writes use `expected_hash=new`; source tree mutations are serialized per site so stale writes are rejected instead of silently overwriting concurrent edits. Git-backed sites can run `website_sync_source` to refresh from the retained source reference. Sync uses the same safe clone path as import, strips Git metadata, validates the imported tree, records a `sync_run`, and blocks with `blocked_local_changes` when the current working tree has unpublished local changes unless the caller explicitly supplies `confirm=true` after review. Diff compares the current working tree against the active revision snapshot. Reference payloads include `app_page` and `/app/website-studio/...` deep links for implemented site, page, route, asset, revision, and publish-request entities. Preview creates a persisted preview record, a runtime health session, and a `preview_url` that points at Website Studio's app-owned `preview-runtime` frontend. Compatible ready previews are reused by route plus runtime build id, or by route plus current static source fingerprint, so normal frontend refresh/navigation does not create duplicate preview records. The runtime frontend fetches `website_preview_document` from the backend, then mounts the selected website HTML in a nested opaque-origin sandbox iframe. Static exports are reported as `runtime_status=ready`; bounded local CSS, static media, and local JavaScript files are inlined into the runtime document, while network connections stay blocked by preview CSP. Preview reads do not emit `maverick.app.data-changed` events.

PHP and Node-build sites use bounded app-owned runtime adapters. `website_build_validate` prepares a runtime build record for `php` and `node_build` sources, copies an immutable runtime artifact, and indexes rendered routes when route rendering succeeds. Successful runtime renders are also crawled for same-origin internal links up to Website Studio's bounded route budget, so PHP/Node sites can surface rendered routes that were not present in the static sitemap. Node asset builds run only when `package-lock.json` is present and the npm `build` script expands to allowlisted local build commands such as Vite, Astro, Gatsby, Next, Dart Sass/PostCSS/CSSNano, Webpack, or a tightly-scoped generated-file `rm`. Build binaries must resolve from the imported site's own `node_modules/.bin`; Website Studio does not fall back to host-global Node binaries. Dependency installation uses `npm ci --ignore-scripts --no-audit --no-fund`; the app contract therefore declares outbound access to `registry.npmjs.org` in addition to GitHub. Arbitrary shell commands, unsupported package managers, native-binary build tools such as `node-sass`, inline credentials, host paths in runtime logs, and unbounded scripts are blocked or redacted before surfacing. PHP preview uses the local `php` executable, an isolated loopback server on `127.0.0.1`, a bounded route request, a short process lifecycle, and the same nested opaque-origin iframe isolation. If `php` is not available in the host runtime, PHP sites are blocked with `php executable is not available to the Website Studio preview runtime` instead of falling back silently.

Publishing now uses explicit Website Studio approval events plus an authenticated actor policy. A publish request requires at least one working-tree diff and a passing deterministic build validation. `website_approval_record` creates one scoped approval for `publish` or `rollback` only for an authenticated Maverick user whose workspace role is owner/admin or whose platform role is admin/operator; `approved_by` must match that actor when supplied. Approvals are single-use and must match the selected site, action, and target id. `website_publish` consumes a publish approval, snapshots the working tree as a published revision, marks the publish request and changeset published, and records a deployment. `website_rollback` consumes a rollback approval, restores the selected revision into the working source tree, records a new rollback revision, and records a rollback deployment.

`website_publish_target_configure` can bind a site environment to a managed static publish target. Approved managed-static publish copies the selected working source into an immutable deployment artifact under `data/website-studio/sites/<site_id>/deployments/<artifact_id>/public`, records a redaction-safe `maverick-managed-static` source reference with explicit generic-hosting binding metadata, and marks the deployment mode as `maverick_managed_static`. Build validation also prepares a static preview artifact under `data/website-studio/sites/<site_id>/builds/<build_id>/public` whenever a static route is available. This implements Website Studio's Phase 3A orchestration boundary: artifact selection, publish request, deployment records, rollback intent, app-owned static/PHP/Node preview runtime adapters, rendered route records, and runtime health records. Generic platform hosting concerns such as custom domains, certificates, CDN/cache policy, public production binding, external deployment writeback, and long-running managed production process hosting are still explicitly recorded as missing generic surfaces until core exposes reusable hosting/runtime surfaces.

GitHub-backed sites with an activated grant receive a redaction-safe `github_pull_request` deployment source reference containing the target base branch, deterministic `maverick/<site_id>/<publish_request_slug>` working branch, commit sha, and pull-request URL unless the environment is explicitly configured for `managed_static`. If a GitHub source is configured for Git PR publishing but the grant or runtime secret delivery is missing, publish is blocked before consuming approval. The app still does not deploy to external hosting providers or run arbitrary production commands. CMS, commerce, external deployment writeback, custom domains, CDN, and certificate automation remain undeclared because they are not implemented.

`website_list_changes` exposes bounded change state for agents: working diff summaries, changesets, publish requests, approval events, build validation records, deployments, and revision metadata for a selected site. It is read-only and does not push, deploy externally, or write back to third-party systems.

## Frontend Layout

The central workspace frame is reserved for the selected website only. It does not show the editor, diff, preview, or publish controls; those operations are handled through agent-facing MCP/CLI/backend surfaces.

When no site exists, or when the user clicks `New website` in the sidebar footer, the central frame shows only two centered actions:

- `Drop ZIP`
- `Connect Git`

`Drop ZIP` supports both file-picker selection and direct drag-and-drop. ZIP bytes are persisted through the resolved Storage provider before Website Studio imports the working copy and stores a Storage artifact reference on the site. `Connect Git` prepares a redaction-safe GitHub connection record and Vault grant requirements before importing the source; private repo clone/push/PR execution requires the activated Vault/Core Secrets grant path described above.

The central preview also shows a compact read-only status overlay with page, route, asset, working-change, runtime, build, request, and deployment state derived from `website_site_status` and `website_list_changes`. It intentionally does not expose production action buttons.

The base-shell sidebar widget owns site navigation. It shows search first, then the site selector, then the selected site's indexed pages, non-page routes such as redirects or sitemap-only routes, assets, and runtime/change status with compact badges. Page, route, and asset clicks use the shell open-app contract with `pages/<id>`, `routes/<id>`, and `assets/<id>` app pages. Files touched by the working diff are marked `modified` in the sidebar. The sidebar footer action is named `New website`.

## Security Notes

- Website paths are normalized and constrained to the selected site source tree.
- ZIP import rejects absolute paths, `..`, ignored system files, excessive file counts, and excessive expanded size.
- Git import rejects inline credentials, allows GitHub HTTPS URLs or local repository paths inside the Website Studio data root, and runs Git with credential prompts/helpers disabled unless a prepared and activated GitHub connection receives its token through Core Secrets for private repository clone.
- GitHub connection preparation and activation store only repository metadata, selected auth mode, secret logical names, and redaction-safe grant references; raw GitHub tokens must stay in Vault/Core Secrets and are never accepted by the frontend.
- Build/preview supports deterministic static validation, immutable preview artifacts, allowlisted npm lockfile asset builds, bounded PHP route rendering when the host provides `php`, and an app-owned isolated preview runtime. Unsupported package managers, arbitrary dependency scripts, arbitrary shell commands, missing PHP binaries, and missing lockfiles fail closed with explicit runtime requirements.
- Publish and rollback approvals are explicit, scoped, single-use app records guarded by authenticated owner/admin or platform admin/operator policy. Public production binding remains blocked until generic platform hosting surfaces exist.
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
maverick app website-studio mcp inspect website_preview_document --json
npm --prefix apps/website-studio run test:visual
```
