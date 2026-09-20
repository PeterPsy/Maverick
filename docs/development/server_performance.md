# Server, Storage and PWA performance verification

The performance work keeps Storage's app-owned inventory separate from Core
usage accounting. The intended local SQLite owners are
`data/storage/inventory.sqlite` inside each workspace and
`data/control-plane/usage/usage.sqlite` for Core. Neither is a cache: file
identities, Memory links, tombstones and usage observations require backup.
Migration is explicit, validated and fenced; ordinary startup and reads must
never perform a cutover. Storage selects its adapter through
`inventory-store.json`; the JSON adapter is retained only for pre-cutover
workspaces and verified reverse exports. Usage still uses its existing adapter
until its independent transactional implementation and cutover are verified.

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
