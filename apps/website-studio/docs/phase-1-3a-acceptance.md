# Website Studio Phase 1-3A Acceptance

This document is the versioned acceptance reference for the Website Studio scope implemented through Phase 3A. It intentionally excludes post-3A platform hosting, CMS, commerce, production process hosting, and third-party deployment writeback.

## Scope Boundary

| Phase | Accepted Scope | Current Status |
| --- | --- | --- |
| Phase 1 | Import, validate, classify, index, preview, search, read, write, patch, diff, references, and active-site workspace context for static website source trees. | Implemented |
| Phase 2 | GitHub connection metadata, Vault/Core Secrets token delivery, sync, publish request creation, scoped approvals, approved publish, approved rollback, revisions, deployments, history listing, and secret redaction. | Implemented |
| Phase 3 App Orchestration | Managed-static publish target records, immutable deployment artifacts, public-binding readiness metadata, and explicit pending status for generic platform hosting. | Implemented app-side only |
| Phase 3A | App-owned static/PHP/Node preview runtime adapters, route rendering, preview document delivery, observability reports, visual navigation, runtime health, retention pruning, and bounded subprocess policy. | Implemented |

## Acceptance Checks

- `app_contract.json` declares `publisher=maverick`, `distribution.mode=source_available`, and `distribution.source_access=forkable`.
- `website_manifest` returns `implemented_phases` containing `phase_1`, `phase_2`, `phase_3_app_orchestration`, and `phase_3a_runtime_preview`.
- `website_manifest` returns `platform_hosting_status=pending_generic_surface` and does not imply public production hosting is available.
- ZIP and Git import reject traversal, symlinks, executables, sensitive files, excessive file counts, excessive expanded size, and inline GitHub credentials.
- GitHub private import and GitHub PR publish require a prepared connection and Vault/Core Secrets delivery of `github-token`; missing delivery blocks publish before approval consumption.
- GitHub PR publish creates a deterministic `maverick/<site_id>/<publish_request_slug>` branch, opens or reuses a PR, and updates existing branches with `force=false`; non-fast-forward conflicts block the publish instead of force-pushing.
- Writes and patches require optimistic concurrency through `expected_hash`; concurrent stale writes are rejected.
- Static preview documents use app-approved file gateway capabilities for local assets and run in a nested opaque-origin sandbox iframe.
- Phase 3A Node builds require `package-lock.json`, run `npm ci --ignore-scripts --no-audit --no-fund`, resolve build binaries from site-local `node_modules/.bin`, and execute only allowlisted build commands.
- Phase 3A subprocesses run with a constrained environment, timeout enforcement, process-group cleanup on POSIX, and best-effort POSIX CPU, memory, open-file, and process limits.
- PHP preview binds only to `127.0.0.1`, uses a short TTL registry, and fails closed when the host does not provide `php`.
- Maintenance pruning can delete only operational preview/build/runtime records and artifacts; it never deletes source trees, revisions, deployment artifacts, publish requests, approvals, or site records.

## Explicit Non-Goals Through 3A

- Public custom-domain provisioning.
- Certificate issuance or renewal.
- CDN/cache policy enforcement.
- Public production binding through a generic platform hosting surface.
- Long-running production server/process hosting.
- CMS/admin backends, commerce flows, payment integrations, or database-backed service emulation.
- External hosting provider writeback or arbitrary deployment command execution.

## Verification

The acceptance suite is anchored by:

```bash
python3 -m unittest discover -s apps/website-studio/tests -p 'test_*.py'
maverick core cli run core.app-sdk.validate --app-root apps/website-studio --json
maverick app website-studio mcp call website_manifest --json
maverick app website-studio frontend build --json
npm --prefix apps/website-studio run test:visual
```
