# PWA cache M4 implementation validation — 2026-08-31

## Status

M4 file-cache mechanics, the parent-mediated Storage integration, aggregate
Settings diagnostics, official generated frontend artifacts, and focused
automated tests are implemented. The product remains in its normal connected
UI: there is no local-file action, badge, mode, alternate shell, or residency
list.

This is an implementation gate, not a private-file rollout approval. The
runtime feature projection remains off, raw Storage bytes remain canonically
`unclassified`, and the server descriptor is therefore ineligible. Storage
also still runs in the existing same-origin frame sandbox. Enabling persistent
private bytes requires a reviewed canonical classification, an opaque or
isolated Storage frame, privacy approval, and physical-device evidence.

No Safari, Home Screen, Dock-container, or other physical-device result is
represented as passed by this record.

## Implementation checkpoints

- `32352cd5` — scoped OPFS byte store, separate IndexedDB manifest, streaming
  writer, strong-validator same-session resume, digest/size verification,
  cache-first reads, budgets/LRU, cleanup, diagnostics, and lifecycle support;
- `271bd602` — private frame protocol, Base Shell broker and policy projection,
  stable local/Drive versions, Storage preview integration, Settings totals,
  failure hardening, tests, and official frontend builds;
- `eb336041` — tri-state feature revalidation that preserves a previously
  confirmed same-session cache path during config transport loss, fails closed
  on cold start, and clears authority on explicit/authentication rejection.

## Closed M4 tasks

| Task | Evidence |
|---|---|
| PWA-060 | Feature-detected `maverick-pwa-file-cache-v1` OPFS adapter with opaque flat names |
| PWA-061 | Separate scoped `maverick-pwa-file-v1` IndexedDB manifest, schema 1 |
| PWA-062 | Best-effort cloned-response stream writer; valid network Blob does not await publication |
| PWA-063 | RAM-only partial session sends `Range` plus exact strong `If-Range`; invalid resume restarts fully |
| PWA-064 | Exact source version, size, strong ETag, and SHA-256 checked before `ready`; hits are re-hashed |
| PWA-065 | Local `sha256:<digest>` and explicit Drive provider revision; modified metadata is not a cache version |
| PWA-066 | Ordinary Storage image/PDF/text/markdown preview path consults cache first without UI branching |
| PWA-067 | 64 MiB entry, 128 MiB scope, 256 MiB origin budgets; LRU and aggregate Settings clear |
| PWA-068 | Eligible raw previews consult the bounded persistent path before the existing RAM/server path; card ceiling remains 8 MiB |
| PWA-069 | Abandoned writes, OPFS orphans, superseded ready versions, corruption, and scoped lifecycle cleanup |
| PWA-070 | Missing or denied OPFS, unknown quota, local setup/write failure, and manifest failure use the network path |
| PWA-071 | No offline-file naming, state, policy, action, promise, badge, or alternate viewer |

## Security and authority

Base Shell owns the host-attested user/workspace/`storage` principal and the
only SDK file-cache host capability. A mounted Storage frame transfers a private
`MessagePort` and supplies only stable file id and source version. The broker
accepts only that exact frame window, independently calls the authenticated
internal descriptor action, validates identity and same-origin media URL,
applies local-persistence policy v2, and verifies returned bytes before
transferring the Blob.

The broker re-reads the exact `maverick.pwa-config.v2` no-store projection for
every open. Explicit false, malformed success, or `401`/`403` clears a prior
positive result. A transport failure may reuse only a positive result already
confirmed by that authenticated in-memory broker, allowing a ready cache hit
during network loss; a cold broker remains fail-closed. Disabled, stale,
denied, oversized, or unclassified descriptors return `unavailable`,
preserving Storage's existing server path. The global flag is not a policy
override: the current backend always projects raw bytes as ineligible until
canonical classification changes through review.

Local media requests carrying the cache marker hash the current file before
serving it, including same-size/same-mtime mutation cases. Drive uses an
explicit provider revision; a modified timestamp is not accepted as a stable
file-cache version. URLs, credentials, secret values, file names, and
principal identities are not persisted in OPFS names or emitted by aggregate
diagnostics.

## Failure and cleanup semantics

A writer uses an unpublished opaque path. Network-stream interruption may
retain a same-session partial, while local setup/write failure cancels and
discards that branch. Publication occurs only after verification. An older
ready version remains until its replacement is ready; initialization repairs
an interrupted obsolete-version cleanup. Denied OPFS initialization disables
persistence for that cache instance rather than failing or duplicating the
ordinary network read.

Least-recent eviction can remove any non-protected ready file to satisfy both
scope and global bounds. Local deletion touches only the file manifest and the
owned OPFS path; it never calls Storage delete or Drive trash. Logout,
authorization failure, user/workspace transition, and Settings clear share the
durable structured/file cleanup barrier. A partial cleanup remains pending and
blocks persistent reuse until deletion succeeds.

## Automated evidence

| Surface | Result |
|---|---|
| PWA cache package typecheck | passed |
| PWA cache package | 10 files, 82 tests passed |
| Base Shell frontend | 28 files, 137 tests passed |
| Base Shell worker/build harness | 13 tests passed |
| Storage frontend | 28 files, 126 tests passed |
| Storage Python selection | 128 tests passed, 10 expected skips |
| Settings generated frontend selection | 14 tests passed |
| PWA config/API/resource inventory selection | 11 tests passed |
| Unused-import and Python/JSON syntax checks | passed |
| Storage official build | `0062ec3f713cf1bad5df0970d792f053b4be8dbf44f4e9971619f759aaf4bde8` |
| Base Shell official build | `64e6217bff6700da15b4f3937b388e770747e93bfed96877823697caa3f715a0` |
| Settings official build | `ae4ff2c315c10549af07e781fa2e28381a53dad212ebb6347db5774ec91243c9` |

The default fast repository suite was executed. M4's Storage selection and
the relevant PWA/config/inventory/Settings shards were green. The aggregate
command remained non-green on the same nine unrelated shared-repository
failures already outside the M3 cache gate: one runtime-process environment
assertion, two existing repository line-budget assertions, two Base
Shell/App Store/Chat fixture or source assertions, and four Senses
provider-selection setup errors. Follow-up M4 hardening was rerun through the
complete SDK, Base Shell, Storage frontend, Storage Python, worker, and focused
Core selections listed above.

## Built artifacts and live projection

The three official app builds produced verified
`maverick.frontend-assets.v2` manifests. The Base Shell worker continues to
bypass API, backend, media/range, SSE, WebSocket, and sidecar requests; OPFS
file bytes are not a worker Cache API responsibility. Each rebuilt app emitted
its scoped `maverick.app.frontend-changed` event.

The observed projection remains:

```json
{"schema":"maverick.pwa-config.v2","service_worker":{"enabled":true,"generation":"v2"},"features":{"data_cache":false,"storage_file_cache":false}}
```

Storage backend entrypoints are fresh subprocess invocations, so the Python
changes need no Core/backend restart. No restart was performed, avoiding
disruption to concurrent repository work.

## Rollout and rollback boundary

M4 is complete with persistent Storage file bytes disabled. A future rollout
must first classify an exact raw-file resource in the canonical inventory,
make the server descriptor eligible only for that reviewed class, move Storage
to an opaque or isolated frame boundary, and record physical browser/device
evidence. Only then may an operator enable
`MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE`.

Rollback sets that feature off and restarts Core through the normal operator
procedure. Every mounted broker rechecks the flag per open; the next explicit
server response disables it, while a device that cannot reach the server can
only use a positive decision already confirmed inside its current authenticated
session. Existing derivatives remain disposable and can be removed by bounded
lifecycle or Settings clear; rollback never deletes server files or clears
unrelated origin storage.
