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
and measured count. Repeat at 1k/100k for scaling. These are isolated service
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

Use SQLite's backup API for the authoritative index, including committed WAL
pages. Read connections use `mode=ro`; short-lived connections can still cause
SQLite shared-memory filesystem traffic. Report that physical I/O separately
from application metadata mutations instead of calling all catalog reads
zero-write. The isolated real-scheduler probe on 100k flat files completed a full
cycle in 37.51 seconds, with a maximum pass of 483.60 ms and both same-size,
restored-mtime external edits discovered. Run `scripts/storage_reconciliation_probe.py`
under the verified SQLite runtime to reproduce. Mounted HTTP, concurrent workloads,
operator backup integration and physical-device release gates still require
their dedicated validation.

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
`cutover`, `backup`, or `rollback`; validate/cutover require the returned
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
