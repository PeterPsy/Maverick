# Server, Storage and PWA performance verification

The performance work keeps Storage's app-owned inventory separate from Core
usage accounting. The intended local SQLite owners are
`data/storage/inventory.sqlite` inside each workspace and
`data/control-plane/usage/usage.sqlite` for Core. Neither is a cache: file
identities, Memory links, tombstones and usage observations require backup.
Migration is explicit, validated and fenced; ordinary startup and reads must
never perform a cutover. Storage selects its adapter through
`inventory-store.json`; the JSON adapter is retained only for pre-cutover
workspaces and verified reverse exports. Usage defaults to its transitional document adapter until the independent
SQLite owner is explicitly prepared, validated and selected with
`MAVERICK_USAGE_STORE=sqlite`.

## Reproducible baseline

`scripts/server_performance_probe.py` creates and deletes its own synthetic
fixture. It never reads or mutates a workspace. Run the same fixture and
runtime before and after an adapter change:

```sh
python3 scripts/server_performance_probe.py --domain storage --count 10000 --requests 500
python3 scripts/server_performance_probe.py --domain storage --count 10000 --shape tree --requests 500
python3 scripts/server_performance_probe.py --domain usage --count 10000 --requests 500
```

The default warmup is five operations. The manifest identifies source commit,
Python/SQLite, CPU count, fixture size and boundary. Report median, p95,
maximum, process physical write bytes, and a separately instrumented Storage
read's `stat`/`scandir` calls. Instrumentation is outside latency timing. Usage
persists every measured distinct observation; its dataset grows by the warmup
and measured count. A separate diagnostic observation follows the timed Usage
run. The `sqlite_transactions` entries report that call's `BEGIN` duration and
transaction duration through commit, split into reads/writes. `BEGIN IMMEDIATE`
includes writer-lock acquisition; deferred reads acquire their read lock later.
These diagnostics include work inside the transaction, not only SQL VM time,
and deliberately exclude connection close/checkpoint time, which remains in the
end-to-end latency and physical I/O measurements. Tracing runs only inside the
probe, never in production. Repeat at 1k/100k for scaling. These are isolated service
measurements, not mounted HTTP, browser, physical-device or release evidence.
Run without unrelated builds, tests or other benchmark workloads.

## SQLite runtime prerequisite

The Python module's loaded library must include the upstream WAL-reset fix.
`core.shared.sqlite_runtime.require_safe_wal_runtime` refuses versions below
3.51.3. Verify the backend, CLI and app subprocess runtime, not just a system
`sqlite3` executable. A local deployment whose system library is older can
build the pinned release without replacing the system library:

```sh
python3 scripts/prepare_sqlite_runtime.py --prefix .maverick/sqlite/3.51.3
LD_LIBRARY_PATH="$PWD/.maverick/sqlite/3.51.3/lib" python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

The build checks SQLite's published SHA3-256 of the amalgamation before
compilation. This command only prepares a library. Selection for all writer
processes and a coordinated backend restart are part of the separate domain
cutover; no deployment is silently changed. WAL requires a local filesystem
and same-host writers, `synchronous=FULL`, short transactions and bounded lock
waits. Back up through SQLite's backup API, never copy just an active main DB.
See [SQLite 3.51.3 release](https://www.sqlite.org/releaselog/3_51_3.html) and
[WAL](https://www.sqlite.org/wal.html).

## Request and lifecycle correctness

Storage catalog reads have a surface-owned controller. Navigation, refresh,
suspension and disposal invalidate older tickets and abort their transports.
Results and `finally` state changes require a current ticket, including a
second deep-link lookup. One page request is admitted per view. Cancellation
is established by local ownership, never by matching browser error strings;
current transport errors remain visible. Mutations already accepted by the
server retain their normal completion semantics.

Widget visibility intersects owning surface activity, sidebar/dock visibility,
document visibility and overlay expansion. Hiding preserves UI state while
suspending reads. A full app-event subscriber queue closes with WebSocket 1013
and `resync_required`; reconnect must reload authoritative state. The six
Core WebSocket families await the existing shutdown controller's notification
instead of polling every 100 ms. Shutdown from another thread or a parent
controller wakes loop-owned events; cancellation unregisters every waiter.

Private PWA cache rollout still requires the existing resource privacy and
physical Safari/macOS/iOS gates. A server or Chromium result cannot satisfy
those gates.

## Storage index and migration

New Storage installations explicitly initialize schema 2. Existing installations
keep their current store until an administrator runs the migration through the
Storage CLI. Inspect `inventory.migration` with `phase=status`, then use
`phase=prepare`, `phase=validate`, and `phase=cutover`, passing the returned
`migration_id` to the last two operations. `phase=rollback` reverse-exports the
current index, including writes made after cutover; it never restores a stale
pre-cutover JSON backup. `phase=recover` handles interrupted filesystem commits.

Preparation snapshots the original JSON with a manifest, imports exact records,
checks duplicate identities/paths and existing content hashes, and verifies
record counts and digests. Cutover rechecks both the source and filesystem
fingerprints under the app's interprocess mutation fence. Catalog readers share
that fence; writers, recovery and migration acquire it exclusively with a
bounded wait. Unsupported schemas and SQLite runtimes fail closed. Neither
ordinary reads nor writes implicitly migrate a workspace.

Indexed catalog and stable-ID resolution never scan document paths or rewrite
the inventory. Filters and deterministic natural sorting precede the SQL limit.
Continuations carry `dataset_revision`; a mismatch returns `catalog_changed`
without an appendable page. `catalog.summary` supplies local root totals, and
`directory.children` provides bounded child/search pages across the selected roots,
with independent folder pagination and exact totals. Upload UUID containers stay
hidden while their files remain discoverable. Exact counts and byte totals
are maintained with file and directory mutations. Custom reference order applies
until an explicit sort is requested. `state.json` remains the small UI-state
store; remote locators, tombstones and Memory links remain in authoritative rows.
Cutover retries preserve writes already accepted by the selected adapter. Reverse
cutover records database retirement in its durable marker, so recovery after that
marker cannot replace subsequent JSON writes with an older export.

Filesystem mutations use durable intents, reserved IDs and atomic replacement
or rename. Success follows metadata commit. Recovery can finish prepared writes,
complete metadata after a filesystem commit, or report a conflict with external
changes. Pending intents block catalog reads and reconciliation until recovered.
Conversions and network transfer remain outside SQLite write transactions.
Indexed quota checks read maintained local byte totals instead of walking both
Storage roots. Image composition runs in app-private scratch outside the mutation
fence, then verifies the source signatures before committing its output.

The existing `background_tick` hook drives a resumable scan capped at 5,000 stat
calls and a 500 ms work budget per invocation. It preserves its directory cursor
and observed names between processes. The normal due interval is 15 seconds; an
unfinished eligible scan requests another pass after one second. Each pass reuses
one SQLite connection and one directory iterator at a time, without retaining
process-local cursors across invocations. Missing subtrees are tombstoned in
bounded batches. Absence is established only after a full,
stable directory enumeration; permission and I/O failures cause retries rather
than tombstones. The signature includes size, nanosecond mtime/ctime, device and
inode. Unchanged observations preserve record timestamps, hashes and revision.

The administrative Storage `inventory.migration` action with `phase=backup`
uses SQLite's backup API for the authoritative index, including committed WAL
pages. It drains mutations, rejects unfinished intents, validates integrity and
identity/metadata digests, and atomically publishes a standalone database plus
manifest under the app-owned `backups/` directory. It backs up inventory metadata;
uploaded/generated file bytes need their separate workspace content backup.
Read connections use `mode=ro`; short-lived connections can still cause
SQLite shared-memory filesystem traffic. Report that physical I/O separately
from application metadata mutations instead of calling all catalog reads
zero-write. The isolated real-scheduler probe on 100k flat files completed a full
cycle in 37.51 seconds, with a maximum pass of 483.60 ms and both same-size,
restored-mtime external edits discovered. Run `scripts/storage_reconciliation_probe.py`
under the verified SQLite runtime to reproduce. Mounted HTTP, concurrent workloads
and physical-device release gates still require their dedicated validation.

## Chat projection and memory

Live event appends reuse the event index and sort only the arriving batch. Duplicate
replay keeps the existing array; corrections and late events use the deterministic
merge path. Transcript projections retain unchanged turn/message objects and rebuild
affected turns; goal updates that amend earlier turns share a dependency group.
There is no strong 80-transcript projection cache. Cold navigation history has an
8-session / 32 MiB estimated-retained-memory LRU, separate from the active thread;
the estimate includes UTF-16 and a conservative allowance for projections/indexes.
No live delta serializes that cache. Frame batching flushes control and terminal
events immediately, and ephemeral Usage snapshots never become replay cursors.

Long visible transcripts use measured variable-height rows with overscan and
spacers. Historical data stays available in memory and through normal paging;
viewport rendering does not truncate the server catalog. Scroll/ResizeObserver
integration requires browser and physical Safari checks before release.

The opt-in `transcript.performance.test.ts` probe reports 500 live updates after
five warmups for 100/1k/5k messages. Set `MAVERICK_PERFORMANCE_PROBE` to an output
path and run that file alone with one Vitest worker. This measures isolated
merge/projection CPU, not browser rendering, startup or server-side batching.

## Background scheduling and idle providers

The backend retains each app hook's bounded `next_due_in_seconds` hint and checks
it before resolving the app surface or launching Python. Failure uses the normal
interval; app revision changes invalidate its deadline, and disabled apps or
workspaces are removed from the schedule. The scheduler waits on shutdown
notification instead of an uninterruptible sleep. Explicit lifecycle hooks keep
their existing immediate semantics.

Delayed prewarm and provider retirement share one in-process idle owner, replacing
per-session Timer threads. Only the latest pending action for an owner/session is
retained. Idle retirement keeps the 180-second TTL and checks pending turns inside
the same persisted lifecycle fence used by queue admission/provider start. Fresh
completion deadlines supersede an expired callback waiting for that fence. A
successful prewarm also schedules retirement when no first turn follows it.

## Usage transaction and operator workflow

The Usage SQLite adapter atomically records deduplication, normalized observations,
stream cursors, root/session totals and hour/day buckets. Indexed predecessor and
successor lookups compensate late cumulative observations without rebuilding a
stream. Numeric latest-request counters are retained for that compensation;
arbitrary provider payloads are not stored. Charts and summaries are read-only.
Deletion subtracts only the selected sessions' contributions in one transaction.
Notifications reuse the runtime bus and the subscriber's asyncio loop: one leading
snapshot, a replaceable trailing snapshot within 500 ms, and immediate terminal
flush. No per-observation durable runtime event or background persistence buffer
is introduced.

Inspect the declared core command `core.persistence.usage-status`. The operator
command `core.persistence.usage-migration` accepts `phase=prepare`, `validate`,
`cutover`, `backup`, `repair`, or `rollback`; validate/cutover require the returned
`migration_id`. Equivalent MCP tools are `core.persistence.usage.status` and
`core.persistence.usage.migration`. Complete prepare/validate/cutover with Usage
producers drained, then restart with the returned `MAVERICK_USAGE_STORE` setting.
The command does not modify service credentials or restart the operator's session.
The fence drains in-flight operations and rejects stale adapter instances.

Preparation archives the document source and preserves canonical sample/quota
identities. Validation checks SQLite integrity, counters and stream cursors.
Cutover verifies that the source is unchanged. Backup uses SQLite's backup API;
reverse export includes all committed post-cutover samples and quotas. Interrupted
promotion and database retirement are retryable. General control-plane migration
excludes the independent Usage owner when SQLite is configured.

The 10k isolated-service probe (`--domain usage --usage-adapter sqlite`) measured
500 observations after five warmups at median 8.54 ms and p95 9.95 ms, with
99,426,304 physical write bytes. The equivalent document baseline was p95
1,300.15 ms and 4,864,696,320 bytes (97.96% fewer writes). These are development
measurements on SQLite 3.51.3, not mounted-HTTP or physical-device acceptance.
Keeping a WAL open across every short-lived connection was rejected after it
caused repeated large checkpoint writes in this workload. Default checkpoint
lifecycle is retained; durability is not weakened to improve the benchmark.


## Preview and Drive work bounds

Preview consumers own their abort signals; only completed results are reusable.
Memory uses a 32 MiB LRU budget, an 8 MiB entry limit, and leases for displayed
blob URLs. Cancellation of one reader cannot poison another reader's result.
Converted PDF/PNG content uses authenticated media streams and atomic server-side
derivatives instead of browser base64 payloads. Two conversion slots bound work;
card thumbnails remain disabled. Full local text is read through a bounded stream
and remains complete for guarded Markdown editing.

Drive search waits 200 ms, invalidates the previous request immediately, and
keeps the same connection/direct-parent scope across continuation tokens. Both
main view and sidebar expose further pages. Unknown remote totals remain unknown;
partial provider searches remain visible. These changes still require mounted
browser and physical Safari validation before a PWA release gate is satisfied.

The 100k Usage isolated-service probe at commit `c1848478` measured median 8.69 ms,
p95 9.94 ms and 102,645,760 physical write bytes over 500 distinct observations
plus five warmups. It confirms the measured hot path is independent of the total
sample count in this fixture; it does not substitute for HTTP concurrency tests.

## Mounted HTTP measurements and startup work

`scripts/server_mounted_performance_probe.py` boots an isolated temporary tenant,
installs the real Storage source, logs in with fixture-only credentials, and
uses authenticated loopback HTTP through `PlatformHost`. It never reads the
active tenant. It supports 500 requests plus warmup and `--concurrent` (four
readers, two writers); `--profile` is a separate sequential diagnostic run.
Frontend assets are copied only for contract validation and are not measured.

Before startup optimization, the 10k flat fixture measured catalog median
215.65 ms / p95 236.14 ms and resolver median 250.74 ms / p95 270.56 ms over
500 requests each. These mounted boundaries have not passed the release gates.
The profile found repeated discovery JSON parsing and unnecessary read-path
imports. Core now caches descriptor parsing with a full filesystem signature,
128-file / 8 MiB source-byte limits, and copies only the requested descriptor.
Authorization is still evaluated on every invocation. A single MCP invocation
builds only the requested app/tool definition; full discovery remains available
for catalog and multi-provider reference search. Storage's service router
loads catalog/reference reads separately from Drive, upload and media actions;
shared OAuth secret names no longer import network clients into inventory reads.
All other actions keep the same governed request and event protocol. Backend
responses without secret writes skip secret-consumer metadata discovery; actual
secret writes still resolve consumers and enforce their declared resource scope.

The next 500-request run measured p95 128.99 ms for catalog and 102.18 ms for
resolver. Reusable app JSON workers are therefore available as an explicit
contract opt-in (`entrypoints.json_worker`), with bounded processes, per-request
authorization/capabilities, correlated responses, cancellation and idle expiry.
Storage shares its existing request handlers with its worker; streams keep the
ordinary backend lifecycle. Enable the field only after deploying its core
support. The mounted probe's `--workers` option changes only its disposable
fixture contract. With workers, 10k sequential reads measured p95 47.29 ms for
catalog and 17.77 ms for resolver. Four-reader/two-writer load still measured
333.46 ms and 194.91 ms respectively. Saturation is reported separately from
the ordinary-read latency gate; browser navigation under continuous writes needs
its own correctness and usability check.
The follow-up removes repeated provider catalog discovery from backend metadata
and shares parsed app surfaces only within each HTTP request, retaining fresh
authorization and contract resolution at every new request boundary.

Mounted profiling also identified an fsync of the auth-session collection on
every authenticated read. Activity timestamps now persist at most every 30
seconds, using a conditional update of activity fields only. Session status,
expiry, active user and workspace authorization are still read on every request;
the optimization never extends session expiry or recreates/revives a concurrently
deleted/revoked session. No in-memory activity queue or timer is introduced.
Collection reads also avoid redundant directory creation and lock-file chmods;
permissions are still applied when needed. Parsed collection caches compare
device, inode, size, mtime and ctime, including same-size external replacements
whose mtime was restored.

Storage's activation also opts out of the optional backend workspace-app catalog;
it never consumes that payload. The trusted app contract controls this choice,
and other apps keep their existing context by default. The mounted probe supports
`--extra-apps N` and `--workspace-catalog` to compare discovery scaling. Empty
dependency declarations avoid loading unused selections. Storage mutations keep
one SQLite connection open until their durable intent, metadata and cleanup
commits finish, then close it before releasing the mutation fence. This avoids
repeated last-connection checkpoints without changing synchronous durability or
retaining connections across requests, migration or rollback boundaries.

The follow-up 500-request Storage probe at `a23ddf54`, with 10k files and 25
additional installed apps, measured sequential p95 23.72 ms for catalog and
10.84 ms for resolver. Both sequential targets pass in this disposable HTTP
fixture. Four-reader/two-writer saturation measured p95 146.30 ms and 219.06 ms;
the plan sets the catalog latency target for the ordinary profile. Concurrent
requests completed without hidden failures or lock timeouts; browser navigation
and pagination under continuous writes still need their dedicated check. Exact totals were verified after both
write phases (10,250 and 10,500 files). These results do not certify browser or
physical-device performance.

`scripts/usage_mounted_performance_probe.py` adds authenticated chart HTTP reads
against a temporary tenant after the real Usage prepare/cutover/bootstrap flow.
It measures `ingest_runtime_usage` separately; observations are internal runtime
calls with synthetic session context, not an invented HTTP write endpoint or a
provider benchmark. `--concurrent` runs four HTTP readers and two producers;
the default runs the two measurements sequentially. Both verify the exact sample
and token totals afterward. Fixture dates stay inside the endpoint's real
30-day window. Use `--count 10000 --requests 500 --warmup 5` under the verified
SQLite runtime, adding `--concurrent` for saturation.

The Usage endpoint reuses the context already authenticated by `PlatformHost`
within that request, while retaining its admin-only authorization and standalone
authentication path. With 10k samples, 500 HTTP reads and 250 concurrent runtime
observations, the follow-up measured p95 36.10 ms for reads and 42.86 ms for
observations. The plan's Usage latency target applies to isolated ingestion. These concurrent
HTTP results remain separate and must not replace that measurement.

At `f81bdc92`, 500 sequential Usage HTTP reads measured p95 3.82 ms and 500
internal observations p95 11.68 ms with a 10k fixture. At 100k, four readers and
two producers measured p95 38.68 ms and 38.22 ms respectively; all 100,255 samples
and 17,544,625 tokens were verified. Storage's 100k mounted fixture, with 26 apps,
measured sequential p95 45.53 ms for catalog and 10.59 ms for resolver.

The isolated Storage matrix also covers 1k, 10k and 100k flat/tree datasets with
500 reads plus five warmups. The 100k cases measured p95 32.25 ms (flat) and
32.80 ms (tree), with no `Path.stat` or `os.scandir` calls in the instrumented
read. These are adapter measurements; database page reads and exact SQL totals
still scale with the selected dataset.

Terminal Usage flushing also covers provider failures and post-execution
cancellation, before the terminal event is published. The recorder remembers
the root destination from its last committed observation, so delivery does not
need to look up a session again during teardown. Chat's variable-height window
preserves the bottom position when content grows and adjusts the reading anchor
only after updated spacer heights commit.

The explicit Usage `repair` phase takes the same exclusive owner fence, saves a
pre-repair SQLite backup, and rebuilds only stream cursors, session totals and
hour/day buckets. Samples, retained numeric provider observations and quotas stay
unchanged. Projection validation runs before the rebuilding transaction commits;
an exception rolls the derived tables back as one unit. Repair never runs from a
chart GET and never migrates the document adapter implicitly. The backup manifest
records whether the repair completed, and an interrupted invocation can be retried.
