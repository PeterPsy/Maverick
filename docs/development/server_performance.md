# Server, Storage and PWA performance verification

The performance work keeps Storage's app-owned inventory separate from Core
usage accounting. The intended local SQLite owners are
`data/storage/inventory.sqlite` inside each workspace and
`data/control-plane/usage/usage.sqlite` for Core. Neither is a cache: file
identities, Memory links, tombstones and usage observations require backup.
Migration is explicit, validated and fenced; ordinary startup and reads must
never perform a cutover. Until their respective cutovers are implemented and
validated, the configured existing stores remain authoritative.

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
