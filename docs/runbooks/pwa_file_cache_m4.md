# PWA Storage file cache M4 operations and acceptance

This runbook covers the automatic, transparent Storage file cache implemented
by M4. It does not authorize a cache-residency product surface, an alternative
application mode, or persistence of unclassified file content. The global
feature gate remains off until the classification, frame-isolation, privacy,
and physical-device gates are complete.

## Owned browser state

- package: `@maverick/pwa-cache`;
- manifest database: `maverick-pwa-file-v1`, version 1;
- manifest stores: `files` and `metadata`;
- byte directory: `maverick-pwa-file-cache-v1` in OPFS;
- OPFS file names: opaque flat SHA-256-derived names ending in `.bin`;
- cleanup barrier: `maverick-pwa-file-cache-cleanup-barrier-v1`;
- policy revision: `maverick.local-persistence-policy.v2`;
- default maximum entry: 64 MiB;
- default authenticated Storage-scope budget: 128 MiB;
- default origin-wide file budget: 256 MiB;
- resumable partial identity: RAM-only writer session plus an unpublished
  `writing` manifest record.

This state contains disposable derivatives. It does not own the Storage
server file, the server-side Drive localization cache, static Cache API
assets, structured M3 payloads, or unrelated origin storage.

## Parent broker and policy gate

The top-level Base Shell creates one broker for the freshly authenticated
user, active workspace, fixed `storage` app id, and bounded private access
lease. Storage sends only `file_id` and `source_version` with a transferred
`MessagePort`. Base Shell accepts a request only from the currently mounted
Storage frame and returns the Blob over that private port.

Before OPFS access, the broker calls the authenticated internal
`file.cache_descriptor` action and validates:

1. exact `maverick.storage-file-cache-descriptor.v1` schema;
2. matching stable file id and source version;
3. same-origin `/api/apps/storage/media` URL with the same identities and the
   cache-specific version-verification marker;
4. bounded size and valid content type/digest;
5. exact local-persistence policy revision, canonical data class, attachment
   provenance, and applicable cache/privacy approvals; and
6. before each open until terminal disable, the tri-state decision from an
   exact no-store `maverick.pwa-config.v2` response.

An explicit `false`, malformed successful response, non-transient HTTP error,
or `401`/`403` terminally disables the mounted broker; an authentication
rejection also clears private cache authority. This terminal state avoids one
known-default-off config request per preview card. Enabling the flag afterwards
requires an authenticated broker remount or shell reload. A transient config
response or transport failure is not an explicit disable: only a positive
decision already confirmed by that authenticated in-memory broker may survive
it. Only transport failure/timeout and HTTP `408`, `425`, `429`, `500`, `502`,
`503`, or `504` are transient. The broker may then reuse only the matching
server descriptor it already validated and retained in its bounded RAM map,
allowing the SDK to attempt a cache-first open without another network
dependency. Descriptors are never persisted, are dropped on explicit
denial/authentication failure, and are cleared with the broker. A cold broker
with no confirmed decision and descriptor remains fail-closed.

Unknown or denied policy returns `unavailable` to the Storage adapter, which
uses its ordinary network path. The current resource inventory classifies raw
file bytes as `unclassified`; the backend therefore returns `eligible: false`
and the feature flag defaults to false. Do not change either gate merely to
exercise the implementation. A reviewed canonical resource classification
and opaque/isolated Storage frame are separate release prerequisites.

## Stable version contract

- Local files are eligible for a stable identity only when Storage has a
  lowercase SHA-256 digest. Their source version is `sha256:<digest>`.
- Google Drive files use the provider revision projected as `source_version`;
  modified time is not a file-cache fallback revision.
- The cache-specific local media request hashes the current file before
  serving it and rejects a stale digest URL.
- A cache-marked Drive media request refreshes current Google metadata before
  validating the requested provider version, persists the normalized revision,
  and returns a strong Storage-controlled ETag.
- The broker rejects a final Blob whose size or expected SHA-256 differs from
  the trusted descriptor.

Files without a stable version remain network-only. A new version has a new
key; the prior ready version remains usable until the replacement is verified,
then becomes an obsolete cleanup candidate. Versions are never concatenated
or published under another identity.

## Read, write, and resume behavior

On a valid ready hit, the package reads the OPFS Blob, verifies exact size and
recomputes SHA-256, updates least-recent access, and returns the ordinary
Storage viewer result without a network request.

On a miss, the network response remains authoritative. If OPFS, quota
headroom, strong ETag, policy, lease, size, and stream support are all valid,
the response is cloned into a best-effort writer. The writer streams bounded
chunks to an unpublished path, records progress, verifies size/digest, and
only then publishes `ready`. Cache completion never delays or replaces a valid
network Blob.

An interrupted transfer may resume only while its writer session remains in
RAM. The next attempt sends `Range: bytes=<written>-` and the exact strong
`If-Range`. A missing/mismatched ETag or content range, `200`, `412`, or `416`
discards the partial and performs a full read. Retryable transport and
`429/502/503/504` outcomes may retain the same-session partial; no request or
resume promise survives reload.

## Storage integration and UI invariants

Eligible raw image, PDF, text, and markdown preview reads consult the broker
before their existing server path. Video and audio retain direct range-capable
streaming so first playback bytes are not delayed by a whole-file Blob. Table,
rendered document, presentation, and spreadsheet derivatives remain in their
existing bounded RAM preview cache unless a future resource policy explicitly
classifies them. Card previews retain their existing 8 MiB read ceiling; the
64 MiB file-cache entry limit cannot widen that eager-listing budget.

Hit and miss use the same modal, skeleton/loading state, text renderer, image
renderer, and terminal error flow. There is no cache badge, pin, availability
state, file list, or manual per-file action.

## Cleanup, budgets, and diagnostics

Initialization resumes durable cleanup markers, removes expired abandoned
writes after their grace period, deletes OPFS orphans, and prunes obsolete
versions. Before a new write, expired/non-ready records are removed and ready
records are evicted in least-recent order until both the 128 MiB scope and
256 MiB global limits fit. The current ready version is protected while a
replacement is in flight.

Logout, `401`/`403`, user change, and workspace change durably clear the
applicable structured and file-cache scope. An interrupted clear remains
`pending` in an independent local barrier and blocks persistent reuse until
the manifest and OPFS deletion complete. Settings **Clear cache** clears only
the owned structured entries, file manifest, and referenced OPFS bytes. It
never calls a Storage delete/Drive trash action and never clears the entire
origin.

Settings may display only aggregate total/structured/file bytes and entries,
origin usage/quota, structured backend, OPFS availability, and pending cleanup
count. File ids, names, content, principals, and residency are prohibited.

## Failure drills

### OPFS unavailable or denied

1. Remove `navigator.storage.getDirectory` or deny OPFS in the test container.
2. Open an otherwise eligible preview with working transport.
3. Confirm the ordinary viewer renders the network Blob and no persistence
   promise or extra UI appears.
4. Confirm Settings reports file storage unavailable without enumerating data.

### Local write or quota failure

1. Inject `QuotaExceededError` into the OPFS writer, return an unknown quota
   estimate, or project usage above the 85% headroom threshold.
2. Confirm the successful network Blob still renders.
3. Confirm no `ready` record or orphan remains after maintenance.

### Interrupted and changed-version transfer

1. Interrupt a stream after at least one chunk and retry in the same session.
2. Confirm `Range` and strong `If-Range` are sent and the final digest matches.
3. Repeat with a changed ETag/source version or invalid `Content-Range`.
4. Confirm the partial is discarded, a full request starts, and the old ready
   version is not overwritten before publication.

### Durable scoped clear

1. Seed two user/workspace scopes and inject a manifest or OPFS delete failure.
2. Trigger logout or Settings clear and confirm status is `pending`.
3. Confirm persistent reads are blocked while unrelated scope/server files
   remain intact.
4. Restore storage, initialize again, and confirm the marker, matching manifest
   records, and referenced/orphan bytes are removed.

## Automated preflight

```bash
npm --prefix packages/pwa-cache run typecheck
npm --prefix packages/pwa-cache test
npm --prefix apps/base-shell test
npm --prefix apps/base-shell run test:service-worker
npm --prefix apps/storage test
python3 -m unittest apps.storage.tests.test_storage_file_cache
python3 -m unittest apps.settings.tests.test_settings_app.SettingsFrontendDistTests
maverick app storage frontend build --json
maverick app base-shell frontend build --json
maverick app settings frontend build --json
```

Also run the focused Core PWA configuration/HTTP file-response tests and the
repository fast validation required by `AGENTS.md`. Evidence contains only
build ids, browser/container versions, UTC time, aggregate byte/request counts,
and pass/fail.

## Rollout and rollback

The runtime projection must remain:

```json
{"schema":"maverick.pwa-config.v2","features":{"storage_file_cache":false}}
```

until canonical classification, privacy review, opaque/isolated Storage frame,
and physical Safari/Home Screen/Dock evidence are approved. Afterwards, the
operator gate is `MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE`. Invalid values fail
closed.

Rollback sets that feature to `off` and restarts Core through the normal
operator procedure. Disabled requests use the ordinary server path. Rollback
does not delete server data and does not use whole-origin clearing; a separate
bounded Settings/lifecycle clear can remove owned derivatives. The M3
structured cache and M2R static worker have independent gates and must not be
disabled as substitutes.
