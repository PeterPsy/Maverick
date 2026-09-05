# Maverick PWA Transparent Cache Product Contract

Status: approved for the M2R corrective gate on 2026-08-31. This document is
the normative product and UI contract for browser caching and transport
resilience. It replaces the M0-M2 network-absence product contract without
rewriting that checkpoint history.

## Product invariant

Maverick is an online application with transparent, best-effort caches. Cache
reuse may improve speed and allow a function that already has every required
valid byte to continue, but it never creates a second application mode.

The shell and every mounted app keep their normal layout, controls, navigation,
and component tree when transport is slow, intermittent, or unavailable. A
browser connectivity hint does not hide an iframe, disable the entire UI,
replace an app icon, or select a different route.

## Observable behavior

| Situation | Required product behavior |
|---|---|
| Verified shell build already cached | Render the same standard shell entrypoint. |
| Fresh read model in an approved cache | Render the ordinary component immediately; revalidate according to resource policy. |
| Stale but still renderable read model | Render the ordinary component and revalidate single-flight. |
| Expired or missing read model | Keep that function's ordinary loading state until the server responds. |
| Valid versioned file bytes already cached | Open them through the ordinary Storage viewer without a special badge or action. |
| File bytes missing or invalid | Keep the ordinary open/loading state while waiting for the server. |
| Prompt, model, agent, provider, tool, or authority dependency cannot reach the server | Keep the owning operation pending only where its normal contract allows; do not report success. |
| Server returns `401` or `403` | Immediately withdraw authenticated frames through the shared shell revocation path, run applicable durable cleanup, and never substitute stale data. |
| Server returns validation or conflict response | Show the function's normal terminal outcome; do not classify it as a transport wait. |
| Useful transport returns | Retry or revalidate internally without a banner, toast, route change, or icon change. |
| First visit without network or verified shell | Allow the browser's normal navigation failure; do not synthesize a Maverick product page. |

Equivalent cached and server responses must be visually indistinguishable
apart from existing domain metadata, such as a timestamp that the feature
already owns.

## Loading contract

The public UI state machine is:

```text
idle
  -> loading
      -> valid cache hit              -> success + internal revalidation
      -> successful server response   -> success
      -> transient transport failure  -> still rendered as loading
      -> terminal HTTP response       -> normal error/authentication outcome
      -> unmount or scope change      -> cancelled
```

Waiting and retry are internal transport substates. They are not product copy,
badges, ARIA announcements, global status, or persisted UI state. A feature
must not reveal expired data merely because transport is unavailable.

## Retry and recovery contract

- Browser `online`, focus, and visibility events are hints, not authority.
- A Maverick response confirms that transport is useful again.
- Idempotent reads may retry with one in-flight attempt per stable request key.
- Backoff is exponential, jittered, and capped; hidden UI suspends
  non-essential attempts.
- Pending attempts live only in RAM and accept cancellation.
- Logout, unmount, user/workspace change, and scope revision cancel pending
  attempts and prevent late results from updating the new scope.
- `401`, `403`, `409`, and `422` are terminal for this classification; cleanup latency cannot rewrite a received authorization response as a transport timeout.
- A `429` or selected `502`/`503`/`504` response is retryable only where an
  explicit resource policy permits it and honors `Retry-After` when present.

## Mutation contract

No action is complete until the server confirms it. This rollout introduces no
persistent mutation queue, background replay, durable draft, or generic retry
of `POST` requests.

A mutation may retry in the current RAM session only when it carries a stable
idempotency key and the server provides deduplication. Otherwise the feature
uses its ordinary terminal/pending contract and never invents local success.

## Prohibited product surfaces

The product must not contain:

- a route, page, shell, dialog, banner, toast, badge, or status dedicated to
  network absence;
- global Online/Offline copy or an app-icon connectivity replacement;
- a “contents on this device” management experience;
- “Available offline”, pin, download-for-later, or equivalent controls;
- state labels such as `Offline`, `To download`, or `Pinned` for cache
  residency;
- global control disabling based on `navigator.onLine`;
- iframe unmounting driven by transport state;
- a persistent outbox or delayed-send promise.

Connectivity-related words may appear in developer diagnostics and test
scenario names, but not as a user-facing application mode.

## Allowed technical surface

Settings may expose aggregate cache-size/quota, hit/miss/stale/expired,
eviction, revalidation, request wait/retry/cancellation duration, and worker
recovery diagnostics plus a bounded **Clear cache** action. That surface
describes disposable storage, does not enumerate supposedly available content,
disclose resource/principal identifiers, or promise persistence. Existing loading
indicators, terminal server errors, and domain timestamps remain allowed.

Cache API, IndexedDB, OPFS, and storage persistence requests are all
feature-detected and best-effort. Failure, denial, quota pressure, corruption,
or eviction must leave the server-first path functional.

The M4 Storage adapter is automatic and invisible: an eligible valid file
copy may satisfy the ordinary viewer, while a denied/missing copy follows the
same loading and server path. It adds no residency label or management list.
Settings may show only aggregate structured/file byte and entry counts plus a
single bounded clear action. The adapter and its parent-owned broker are
implemented behind `features.storage_file_cache`; the flag remains off and the
server returns an ineligible descriptor for unclassified or unapproved bytes.
A host-attested platform/workspace admin can approve only one exact current
file/version as `workspace_internal`; revocation, version change, oversize, or
missing approval fails closed. A future rollout must select reviewed
exact-resource approvals and complete privacy and physical-device evidence
rather than interpreting the feature flag as a policy override.

## Authority and privacy

Cached data is derivative and cannot authorize workspace access, capabilities,
provider/model admission, tools, egress, confirmation, revocation, or a
mutation. Tokens, credentials, signed URLs, Browser sessions, Speech audio,
temporary archives, and agentic control-plane state never enter persistent PWA
stores.

Private read models require a top-level-host-attested user/workspace/app
identity, complete resource scope, app-owned resource schema revision,
canonical classification, stable server revision, bounded TTL and byte budget,
sanitization on network and cache reads, durable invalidation/cleanup, and any
required privacy approval. A missing, malformed, stale-disallowed, or expired
condition is a cache miss. An incomplete durable clear is never success and
blocks persistent cache access until deletion is confirmed.

Mounted app and widget documents run on authenticated per-app, per-session
isolated origins. Direct non-shell app documents on the platform origin are
blocked, public app artifacts are sandboxed when interpreted as documents, and
the shell accepts frame messages only from the registered window plus its exact
isolated origin. `allow-same-origin` grants access to the app's isolated origin,
not to the shell's browser storage. Private persistence still requires the
resource, privacy, lifecycle, and rollout gates above; origin isolation alone
does not authorize caching.

M5 structured app adapters are parent-mediated. Base Shell binds the principal
and owns IndexedDB; an accepted child receives only conditional network-read
requests over a private channel and returns its sanitized read model. A cached
catalog or content record cannot enable an authoritative action, and a legacy
value cannot paint until the parent verifies its scoped migration. The pilot
resource and rollout contracts are defined in
`docs/product/pwa_cache_resource_inventory.v2.json` and
`docs/runbooks/pwa_data_cache_m5.md`.

## Acceptance contract

Automated and physical-device checks must prove:

1. the standard shell and mounted app frames remain present across transport
   changes;
2. a valid cache hit renders the ordinary feature component;
3. a miss plus transient failure remains in ordinary loading;
4. recovery resolves or revalidates without global connectivity UI;
5. terminal HTTP outcomes are not hidden as loading;
6. retries are bounded, single-flight, and cancelled at lifecycle/scope
   boundaries;
7. worker update, corruption recovery, and kill-switch cleanup affect only
   owned static-cache namespaces;
8. no cached control-plane value is used as authority;
9. app frames cannot address shell-owned IndexedDB/OPFS or impersonate another
   registered app-frame message source; and
10. the same behavior holds in supported Safari and installed Home Screen/Dock
   containers, assessed separately.

The release record contains only device/browser/build/time and pass/fail or
redaction-safe performance counters. It contains no workspace, user, content,
file, token, or record identifiers.

## Operational maintenance contract

The source-controlled `pwa_cache_operational_policy.v1.json` is the release
authority for frontend/runtime byte ceilings, retry classifier and attempt cap,
reviewed retrying mutations, rollout suffixes, and the physical-device matrix.
CI rejects an oversized committed asset, drift from SDK budgets, a cacheable
unclassified/credential resource, or an unregistered mutation retry contract.

Progressive rollout may narrow an enabled boolean flag by deterministic
workspace and user percentages. It does not change classification or privacy
policy. Invalid percentages and missing identities for partial cohorts fail
closed, and cohort inputs are never exposed in configuration or telemetry.
Rollback disables the narrowest boolean gate first and must preserve the normal
server path; deleting browser data is not a prerequisite. Physical Safari and
installed-container evidence must be complete and no older than the policy
window. Automated browser emulation is supplemental only.
