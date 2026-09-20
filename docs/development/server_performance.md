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
`directory.children` provides bounded child pages. Exact counts and byte totals
are maintained with file and directory mutations. Custom reference order applies
until an explicit sort is requested. `state.json` remains the small UI-state
store; remote locators, tombstones and Memory links remain in authoritative rows.

Filesystem mutations use durable intents, reserved IDs and atomic replacement
or rename. Success follows metadata commit. Recovery can finish prepared writes,
complete metadata after a filesystem commit, or report a conflict with external
changes. Pending intents block catalog reads and reconciliation until recovered.
Conversions and network transfer remain outside SQLite write transactions.

The existing `background_tick` hook drives a resumable scan capped at 5,000 stat
calls and a 500 ms work budget per invocation. It preserves its directory cursor
and observed names between processes. Absence is established only after a full,
stable directory enumeration; permission and I/O failures cause retries rather
than tombstones. The signature includes size, nanosecond mtime/ctime, device and
inode. Unchanged observations preserve record timestamps, hashes and revision.

Use SQLite's backup API for the authoritative index, including committed WAL
pages. Read connections use `mode=ro`; short-lived connections can still cause
SQLite shared-memory filesystem traffic. Report that physical I/O separately
from application metadata mutations instead of calling all catalog reads
zero-write. Mounted HTTP, concurrent workloads, freshness at 100k entries,
operator backup integration and physical-device release gates still require
their dedicated validation.

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
