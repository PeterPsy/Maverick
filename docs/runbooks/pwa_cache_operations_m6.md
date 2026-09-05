# PWA Cache M6 Operations, Rollout, And Recovery

This runbook operates M6 hardening for Maverick's transparent browser caches.
It does not define a network-absence mode, guarantee local availability, or
turn cached data into authority. The normative limits and reviewed mutation
retry registry are in
`docs/product/pwa_cache_operational_policy.v1.json`.

## Aggregate dashboard

Open **Settings → Cache** from the authenticated Base Shell. Settings runs on
an isolated app origin, so it cannot inspect shell storage directly. It opens a
private `MessageChannel`; Base Shell accepts diagnostics and clear requests
only from the exact registered Settings frame, origin, workspace, and shell
session generation.

The dashboard reports only aggregate counters:

- static, structured-data, and file-cache hit/miss/error activity;
- stale and expired reads plus changed/unchanged revalidation;
- eviction count and bytes, current origin usage/quota, and quota errors;
- pending request waits, average/maximum duration, retry attempts, resolved
  waits, and cancellations; and
- worker install, update, recovery, and error counts.

Counters contain no URL, file name, subject, record id, cache key, principal,
payload, token, or content. Each shell tab writes an opaque, independent metric
shard qualified by reset generation; dashboard reads merge all current shards,
so concurrent tabs never overwrite one another. A shared reset-generation
marker is the linearization point for **Clear cache**. Cleanup rereads the
winning marker before pruning, and only touches keys captured before that
decision. A losing concurrent reset therefore cannot remove a shard written in
the winning generation; stale writers remain ignored. The service worker sends
each fixed metric to one window client rather than broadcasting it to every tab,
preventing duplicate counts. Aggregate counters and pending-count/oldest-time
summaries remain
eligible for aggregation for at most seven days in the shell origin; expired
or superseded shards are ignored and winning reset cleanup prunes captured old
generations best-effort. Active wait keys are
salted hashes held in RAM and are never persisted.

`pwa_revalidate_error` counts only a conditional loader failure; cancellation
does not count. Local cache, quota, and cache-write failures use the separate
`pwa_data_cache_error`/quota dimensions and never masquerade as a network
revalidation failure. **Clear cache** cancels pending RAM retry, clears
the owned structured and file stores through the durable lifecycle barrier,
and, only after complete cleanup, resets the aggregate counters. It does not
delete server files, static shell assets, or unrelated origin storage.

Treat `pending` cleanup as a failure to complete, not success. Persistent reads
stay blocked by the cleanup marker until a later clear confirms deletion.

## Automated hardening gate

Run before every rollout change and whenever an app or frontend asset is added:

```bash
python3 scripts/audit_pwa_cache.py
python3 -m unittest \
  tests.unit.scripts.test_audit_pwa_cache \
  tests.unit.scripts.test_pwa_device_regression
npm --prefix packages/pwa-cache run typecheck
npm --prefix packages/pwa-cache test -- --maxWorkers=1
npm --prefix apps/base-shell test -- --maxWorkers=1
npm --prefix apps/base-shell run test:service-worker
npm --prefix apps/settings test -- --maxWorkers=1
python3 scripts/pwa_shell_cache_smoke.py
```

The policy audit verifies every committed frontend manifest and file digest,
per-asset/total/precache budgets, SDK default budgets, the complete canonical
data-class policy, and a bidirectional match—including the complete ordered
invalidation-alias list—between the product inventory and the JSON manifest
consumed by Base Shell's `RESOURCE_DECLARATIONS`. It also scans production
JavaScript, TypeScript, Vue, and Svelte sources across apps, shared packages,
Core, and scripts. Raw or legacy retry-contract objects are forbidden: each use
must call the SDK executor factory with a literal audit id, method, endpoint,
and action, and the operational policy, runtime JSON registry, client/server
evidence, and replay test must agree exactly. CI runs the same audit and the
complete SDK/chaos, broker, worker, Settings DOM, and authenticated
isolated-frame smoke suites. An arbitrary callback passed to
`RetryCoordinator.runOpaque()` remains one-shot and cannot provide method or
retry metadata. Automatic safe HTTP reads use `runRequest()` with a nominal
SDK executor that alone issues GET/HEAD/OPTIONS. A retried mutation can only use
`runMutation()` with a nominal `createMutationRetryExecutor()` result from the
non-overridable registry. The SDK snapshots exact JSON semantics, derives the
fingerprint, injects a stable idempotency key, and owns `fetch`, method,
endpoint, headers, body, timeout, redirects, and decoding. `runMutation()`
accepts neither an operation callback nor a custom classifier.

The `hardeningChaos.test.ts` suite injects uncertain quota, LRU pressure,
corrupt persisted payloads, and intermittent transport. A valid server response
must survive every cache failure; corrupt bytes must be deleted before render;
retry remains single-flight and rate-limited.

## Progressive workspace/user rollout

Boolean flags remain the primary kill switches. Private data and file cache
flags remain off unless explicitly enabled:

```text
MAVERICK_FEATURE_PWA_DATA_CACHE
MAVERICK_FEATURE_PWA_APP_CACHE_<APP_ID>
MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE
```

Every PWA flag also accepts independent integer cohort controls:

```text
<FLAG>_ROLLOUT_WORKSPACE_PERCENT=0..100
<FLAG>_ROLLOUT_USER_PERCENT=0..100
```

An omitted percentage means 100% of an already-enabled flag, preserving the
boolean gate's behavior. Empty, malformed, fractional, negative, or greater
than 100 values select nobody. A partial workspace/user percentage requires
that exact resolved session identity; anonymous or missing identities fail
closed. Cohorts use a stable salted SHA-256 bucket per feature and dimension,
so increasing a percentage is monotonic. Workspace and user controls intersect.
Neither identifiers nor bucket values appear in `/api/pwa/config` or telemetry.

Recommended progression for one reviewed resource is 1%, 5%, 25%, 50%, then
100%, with a full observation window and physical matrix at each release gate.
Change one worker/schema/adapter dimension at a time. Confirm server-first
behavior with both boolean gates off before entering a cohort.

Example for a 5% workspace / 25% user Website Studio cohort:

```text
MAVERICK_FEATURE_PWA_DATA_CACHE=1
MAVERICK_FEATURE_PWA_DATA_CACHE_ROLLOUT_WORKSPACE_PERCENT=5
MAVERICK_FEATURE_PWA_DATA_CACHE_ROLLOUT_USER_PERCENT=25
MAVERICK_FEATURE_PWA_APP_CACHE_WEBSITE_STUDIO=1
```

After changing environment-backed flags, restart Core through the deployment's
normal service procedure, verify `/health`, then fetch `/api/pwa/config` from an
authenticated target session. Reload Base Shell so its registry and brokers use
the new decision.

## Rollback order

1. Set the affected per-app boolean flag to `off`; for an emergency cohort
   stop, set either percentage to `0`.
2. If multiple structured adapters are affected, disable
   `MAVERICK_FEATURE_PWA_DATA_CACHE`.
3. Disable `MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE` independently for file
   cache faults.
4. Restart Core if the deployment reads environment only at process startup,
   verify `/health`, and reload an affected shell.
5. Confirm ordinary server-first reads and loading remain functional. Do not
   delete cache bytes as a prerequisite for rollback.
6. If data removal is required, use Settings **Clear cache** and require a
   complete result. Never clear the whole origin.

Roll back immediately for cross-scope reads, authorization from cache, an
expired render, unredacted metrics, retry storms/duplicates, a failed cleanup,
or any cache failure that blocks a valid network response.

## Worker recovery and kill switch

For one corrupt or missing static entry, ask the active worker to repair its
declared precache:

```js
navigator.serviceWorker.controller?.postMessage({type: "MAVERICK_RECOVER"})
```

Require `MAVERICK_SW_RECOVERED`; `MAVERICK_SW_RECOVERY_FAILED` preserves every
entry that still verifies and increments only a fixed error counter. Recovery
messages and metrics never include an asset URL.

If worker behavior itself is unsafe, set
`MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2=off`, restart Core, and load the shell
with working transport. The client unregisters `/sw.js` and deletes only
`maverick-static-v2:*`, `maverick-app-static-v2`, and
`maverick-base-shell-v3`. It must not touch IndexedDB, OPFS, or an unrelated
Cache API namespace. Re-enable only after the candidate build passes atomic
install, interrupted update, corruption, recovery, and rollback drills in
`docs/runbooks/pwa_shell_v2.md`.

## Periodic physical-device regression

Physical evidence is required at least every 90 days and for a worker protocol,
browser minimum, cache schema, or private-resource rollout change. Create the
canonical matrix template:

```bash
python3 scripts/pwa_device_regression.py template \
  --release-id "$RELEASE_TAG" \
  --output /secure/release-evidence/pwa-device-regression.json
```

Run every generated scenario on the listed physical minimum/current Safari
browsers, macOS Dock app, iPhone Home Screen app, and Chrome/Edge browser and
app containers. Browser profiles also include the private-storage degradation
check declared by policy. Emulation is development evidence only. Fill only
release id, UTC time, OS/browser version, and pass/fail. Then enforce freshness,
completeness, and redaction:

```bash
python3 scripts/pwa_device_regression.py verify \
  --input /secure/release-evidence/pwa-device-regression.json \
  --expected-release-id "$RELEASE_TAG"
```

The verifier first requires the evidence `release_id` to equal the exact
candidate tag/build passed on the command line. It also rejects missing/failing
scenarios, duplicate or missing profiles, stale evidence, every undeclared
diagnostic field, URLs, user/record ids, file names, serials, email, tokens, and
content. Evidence for an older or unrelated build cannot unlock a candidate. A
release stays blocked when the physical lab has not produced a current passing
record; an emulated run must never be relabeled physical.

Store the current redaction-reviewed JSON in the repository variable
`PWA_DEVICE_EVIDENCE_JSON` and its exact candidate identity in
`PWA_DEVICE_RELEASE_ID` for scheduled verification, or pass both explicitly to
**PWA Physical Device Release Gate**. Release events derive the expected
identity directly from `github.event.release.tag_name`; reusable and manual
runs require `release_id`. Every path invokes the same exact-match verifier and
fails closed when identity or evidence is absent, stale, incomplete, failing,
or non-redacted.

Promote an existing GitHub prerelease only through **Promote PWA Release
Candidate**. Its `physical-device-gate` reusable job receives the exact tag,
and `promote-release` has a hard `needs` dependency before it can change that
same tag from prerelease to release. The release-event runs remain independent
detection for an out-of-band publication; they are not represented as the
preventive gate. A green emulated/browser smoke never substitutes for physical
evidence.
