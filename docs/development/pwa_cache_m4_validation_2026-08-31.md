# PWA cache M4 implementation validation — updated 2026-09-01

## Status

The M4 implementation checkpoint and the correctness/security remediation from
the independent review are complete. The automatic Storage file cache, parent
broker, aggregate Settings diagnostics, exact-version approval path, live-hit
revalidation, cross-tab cleanup/concurrency protocol, and per-app browser-origin
isolation are implemented and covered by deterministic tests.

This record does **not** declare the complete M4 rollout Definition of Done.
`features.storage_file_cache` remains false. Raw Storage bytes remain
`unclassified` and ineligible unless a host-attested admin has approved the
exact current representation. No Safari/macOS, Dock, iPhone/Home Screen, or
other physical-device result is represented as passed here. Those physical and
privacy/rollout approvals remain external release evidence.

The product continues to use its ordinary UI: there is no local-file action,
badge, mode, alternate shell, availability promise, or residency list.

## Review remediation

| Review finding | Implemented closure |
|---|---|
| Cleanup could be undone by an active writer | Cleanup advances a durable epoch, broadcasts cancellation, acquires/drains affected writer locks, keeps the tombstone pending through acknowledgement and deletion, and every writer rechecks the epoch immediately before publication. |
| Concurrent budget and versions were uncoordinated | Writers reserve their full declared size under a shared origin-budget Web Lock, coordinate by file identity/generation, recheck budgets after publication, and discard a late older generation instead of deleting a newer ready version. |
| Ready hits skipped authoritative revalidation | Every candidate hit verifies the physical OPFS size/SHA-256 and performs a conditional authoritative media `HEAD`; local media live-hashes the file and Drive refreshes provider revision before answering. |
| Same-origin frames could read shell storage | Every app and widget document now uses an authenticated per-app, per-login-session isolated origin. Direct non-shell app documents on the platform origin are blocked and shell messaging validates exact frame window plus exact origin. |
| No positive production eligibility path | Internal host-role-attested approve/revoke actions govern one exact current file/version, project approved bytes as `workspace_internal`, redact actor identity, fail closed on version change/oversize, and are tested end to end. |
| Plan/runbook statements were stale | Architecture, ADR, product contract, runbook, Storage README, this record, and the workspace Storage plan were reconciled with the implementation. OPFS names are correctly documented as random UUID-derived. |

## Implementation commits

- `32352cd5` — original scoped OPFS store, manifest, writer, resume,
  verification, cache-first reads, budgets, cleanup, diagnostics, and lifecycle;
- `271bd602` — original Base Shell broker, Storage integration, Settings totals,
  stable local/Drive identity, tests, and artifacts;
- `eb336041`, `7663fad0`, `d527e4c9`, `cd668837` — fail-closed gate and
  same-session transport-loss hardening preceding the review;
- `e8eba88d` — durable cleanup epochs/writer drain, atomic reservations,
  file-identity generations, post-publication budget enforcement, physical-hit
  verification, authoritative conditional revalidation, and deterministic race
  tests;
- `b8cf31b3` — durable exact-file/version cache-policy approval and revocation,
  admin/confirmation enforcement, positive eligible descriptor path, local
  live-hash and Drive live-revision coverage;
- `4fb04e27` — per-app/session isolated browser origins for all app and widget
  frames, one-shot bootstrap, session/generation revocation, strict message and
  CSRF/WebSocket boundaries, OAuth relay, public-document sandboxing, mobile
  layout bridge, updated app senders, tests, and rebuilt artifacts;
- `790943ae` — repository/source-contract fixtures aligned with direct-document
  denial and the isolated launch protocol.

## Closed automated M4 tasks

| Task | Evidence |
|---|---|
| PWA-060 | Feature-detected `maverick-pwa-file-cache-v1` OPFS adapter with random opaque flat names |
| PWA-061 | Separate scoped `maverick-pwa-file-v1` IndexedDB manifest, database version 1 and record schema 2 |
| PWA-062 | Best-effort cloned-response stream writer; valid network Blob does not await publication |
| PWA-063 | RAM-only partial sends `Range` plus exact strong `If-Range`; invalid resume restarts fully |
| PWA-064 | Exact source version, size, strong ETag, and SHA-256 checked before `ready`; candidate hits are physically re-hashed and authoritatively revalidated |
| PWA-065 | Local `sha256:<digest>` and explicit Drive provider revision; modified metadata is never a cache version |
| PWA-066 | Ordinary Storage image/PDF/text/markdown preview consults the broker without UI branching; exact approved resources provide a real positive path |
| PWA-067 | 64 MiB entry, 128 MiB scope, 256 MiB origin budgets with atomic reservations, post-publish enforcement, LRU, and aggregate Settings clear |
| PWA-068 | Eligible raw previews consult the bounded persistent path before the existing RAM/server path; card ceiling remains 8 MiB |
| PWA-069 | Cleanup epochs/drain acknowledgement cover active writers; abandoned writes, OPFS orphans, obsolete generations, corruption, and scoped lifecycle cleanup are repaired |
| PWA-070 | Missing/denied OPFS, unknown quota, local setup/write failure, manifest failure, and transient revalidation remain bounded fail-safe paths |
| PWA-071 | No offline-file naming, state, policy, action, promise, badge, or alternate viewer |

## Security and authority

Base Shell owns the host-attested user/workspace/`storage` principal and the
only SDK file-cache host capability. A mounted Storage frame transfers a
private `MessagePort` and supplies only stable file id and source version. The
broker accepts only the registered frame window at its exact isolated origin,
independently calls the authenticated descriptor action, validates identity and
the platform media URL, applies local-persistence policy v2, and verifies bytes
before transferring the Blob.

Until a terminal decision, the broker reads the exact
`maverick.pwa-config.v2` no-store projection for each open. Explicit false,
malformed success, non-transient HTTP failure, or `401`/`403` clears prior
authority and terminally disables that mounted broker. A transient response or
transport failure may reuse only a positive decision and exact descriptor
already validated in the same bounded authenticated RAM broker. A cold broker
remains fail-closed.

Raw bytes default to `unclassified`. `file.cache_policy.approve` requires
`confirm: true`, the current exact source version, and a host-attested
platform/workspace admin. The durable rule applies only to that file/version as
`workspace_internal`; it does not survive a version change. Revocation removes
the rule, entries above 64 MiB are ineligible, and public responses do not
expose the approving actor. These internal actions are not declared through
CLI or MCP and the global feature flag is not a policy override.

Local revalidation hashes the current file, including same-size/same-mtime
out-of-band mutations. Drive obtains current provider metadata and persists the
normalized revision before comparing it with the requested version. Candidate
OPFS bytes are also independently size/digest checked. URLs, credentials,
secret values, file names, and principal identities are not encoded in OPFS
names or emitted by aggregate diagnostics.

Every app/widget frame is bootstrapped from `about:blank` by a one-shot body
ticket onto a distinct app/session origin. The host-only HttpOnly cookie is
bound to actor, workspace, app generation, platform login session, and exact
host. Logout or stale authorization invalidates it. Unsafe proxied requests
require exact isolated `Origin` and browser same-origin proof; WebSockets check
the exact origin. Core injects an exact-parent shell-message relay, Base Shell
validates exact `source` plus `origin`, and public app artifacts cannot execute
as platform-origin documents because their document interpretation is sandboxed
and `nosniff`.

## Concurrency, cleanup, and failure semantics

A writer uses an unpublished random opaque path. Under the common budget lock
it reserves the complete descriptor size before streaming. File generations
make the newest started version authoritative, and publication checks the
generation, cleanup epoch, digest, size, and budget again. The post-publication
budget pass prevents aggregate oversubscription.

Cleanup publishes a durable pending marker before cancellation, broadcasts to
other tabs, drains the affected writer locks, deletes matching manifest/OPFS
state, and clears the marker only after acknowledgement. An old writer cannot
publish after the clear reports complete. Local deletion never calls Storage
delete or Drive trash and never clears unrelated origin data.

## Automated evidence

| Surface | Result |
|---|---|
| PWA cache package typecheck | passed |
| PWA cache package | 10 files, 89 tests passed |
| Base Shell frontend | 29 files, 141 tests passed |
| Base Shell worker/build harness | 13 tests passed |
| Storage frontend | 28 files, 126 tests passed |
| Storage Python selection | 130 passed, 10 expected skips |
| Settings generated frontend selection | 14 tests passed |
| Isolated app-frame/app-mount focused selection | 48 tests passed |
| Widget integration at integration level | 10 tests passed |
| Unused-import, Python syntax, typecheck, and diff checks | passed |
| Repository fast suite | executed; isolation-related fixture failures repaired and affected shards green; three unrelated repository assertions remain |

Deterministic tests cover all three reproduced races: cleanup versus a paused
writer, two concurrent full-budget writers, and a late older version versus a
newer ready version. They also cover live local/Drive hit revalidation,
approval/revocation, ticket replay, direct-document denial, session/logout
revocation, host binding, CSRF, WebSocket origin enforcement, OAuth callback
relay, HTML security headers, and exact frame messaging.

All 18 affected app frontends typechecked/built successfully: Agents, App
Store, Calendar, Chat, Checklist, CRM, Design Studio, Docs Studio, Dynamic
Views, Fitness Coach, Mail, Memory, Senses, Settings, Skills, Storage, Vault,
and Website Studio. Generated `dist` artifacts are committed. Conservative
frontend asset manifests were regenerated where the normal npm build does not
produce them. This update does not claim new official Core build-event hashes;
the earlier three hashes describe the preceding M4 checkpoint, not the
cross-origin rebuild.

The full fast run initially exposed stale direct-mount/source fixtures in the
app-frame change set; those fixtures were corrected. The complete unit/API
shard then passed 306/306, the complete Senses hosted E2E shard passed 4/4, and
the three affected Base Shell source-contract tests passed. A runtime temporary
directory cleanup error from the aggregate run passed on immediate focused
rerun. The remaining non-green results are outside this change set: two existing
repository line-budget contract assertions and one Chat attachment-menu source
assertion being changed by concurrent work.

## Live projection and restart

The required projection remains:

```json
{"schema":"maverick.pwa-config.v2","service_worker":{"enabled":true,"generation":"v2"},"features":{"data_cache":false,"storage_file_cache":false}}
```

The running Core health and public no-store projection were checked on port
8014 and matched the JSON above. Core was not restarted in this turn because
other agentic sessions were active in the same service cgroup; restarting it
would have interrupted their work. The Python app-frame host changes therefore
become live at the next normal operator restart. This record does not claim a
live isolated-origin smoke against the still-running pre-change process.

## Rollout and rollback boundary

The automated implementation/security checkpoint is closed, but M4 rollout is
not declared complete without physical Safari/macOS, Dock, and iPhone/Home
Screen evidence plus the applicable privacy/release approvals. The exact
resource approval path and isolated-origin boundary now exist; they do not
justify changing the default-off global flag.

Rollback sets `MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE=off` and restarts Core
through the normal operator procedure. A broker that has not already reached a
terminal decision rechecks the flag on its next open; explicit disable then
disables that broker for the rest of its mount. Existing derivatives remain
disposable and can be removed by bounded lifecycle or Settings clear; rollback
never deletes server files or clears unrelated origin storage.
