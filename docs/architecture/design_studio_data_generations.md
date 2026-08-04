# Design Studio OpenDesign Data Generations

Status: Accepted (G4)

Date: 2026-08-03

## Scope

This ADR freezes coordinated OpenDesign bundle and data cutover, crash recovery,
retention, and rollback for Design Studio. OpenDesign migrations are
forward-only: an older bundle must never open a directory already migrated by a
newer bundle.

The decision applies to controlled fixtures and copied generations until WP6 is
implemented and verified. It does not authorize migration of a real workspace.

## Decision

The active OpenDesign instance is selected by one app-owned `control.json`.
Its `active` object is an indivisible triple:

```text
(bundle_artifact_sha256, od_version, data_generation)
```

The control file is replaced atomically. A symlink, directory name, modification
time, bundle manifest alone, or "newest generation" heuristic never selects the
active instance. The launcher resolves both the immutable artifact and the data
directory from the validated triple and refuses to start if either reference is
missing or unverified.

## Layout

The app-owned layout under `data/design-studio/opendesign/` is:

```text
control.json
instances/
  gen_<id>/
    data/
backups/
  migration_<id>/
migrations/
  migration_<id>.json
legacy-project-map.json
```

`instances/<generation>/data/` is the only directory passed as `OD_DATA_DIR`.
The generation directory and its `data/` child must be real directories below
the app data root; symlinks are rejected. Staging and previous generations are
not mounted into an active sidecar.

Bundle artifacts are immutable installation assets outside this writable data
tree. Their digests must be present in the core-verified artifact set before a
triple can be parsed, written, activated, recovered, or rolled back.

## Control schema

The complete schema is:

```json
{
  "schema_version": "1",
  "active": {
    "bundle_artifact_sha256": "<lowercase sha256>",
    "od_version": "0.16.1",
    "data_generation": "gen_<id>"
  },
  "previous": {
    "bundle_artifact_sha256": "<lowercase sha256>",
    "od_version": "0.10.1",
    "data_generation": "gen_<id>"
  },
  "migration_id": "migration_<id>",
  "updated_at": "<RFC3339 with timezone>"
}
```

For the first bootstrapped generation only, `previous` and `migration_id` are
both `null`. After any cutover they are both required. `active` and `previous`
must differ. Unknown, duplicate, missing, malformed, oversized, non-UTF-8, or
non-JSON input is rejected. The parser verifies every referenced generation and
artifact before returning a usable control record.

The app-owned implementation is
`apps/design-studio/service/opendesign_generation_control.py`. It performs
strict schema parsing, reference validation, no-follow regular-file reads,
same-directory temporary writes, file flush and `fsync`, atomic `replace`, and
directory `fsync`.

## Migration journal

WP6 writes `migrations/<migration_id>.json` before changing `control.json`. The
journal is strict app-owned metadata with this logical content:

```json
{
  "schema_version": "1",
  "migration_id": "migration_<id>",
  "state": "prepared",
  "source": {
    "bundle_artifact_sha256": "<sha256>",
    "od_version": "0.10.1",
    "data_generation": "gen_<id>"
  },
  "target": {
    "bundle_artifact_sha256": "<sha256>",
    "od_version": "0.16.1",
    "data_generation": "gen_<id>"
  },
  "source_snapshot": "backups/migration_<id>",
  "checks": {},
  "created_at": "<RFC3339>",
  "updated_at": "<RFC3339>"
}
```

The state machine is `prepared -> cutover_committed` or
`prepared -> aborted`. Rollback has a new journal whose source is the forward
triple and whose target is the retained previous triple; it never edits the
original migration journal into a different history.

Journal writes use the same atomic file protocol as `control.json`. The journal
records inventory, checksums, health, DB verification, project smoke, legacy
mapping counts, and redaction-safe errors. It contains no cookie, provider key,
bootstrap secret, prompt, or arbitrary host path.

## Cutover protocol

For 0.10.1 to 0.16.1, WP6 must execute this order on fixture or controlled
copies before any real-data authorization exists:

1. Acquire the Design Studio migration lock; reject new mutating operations.
2. Wait for active runs or cancel them under the declared policy.
3. Stop the active sidecar and prove it is no longer holding the data root.
4. Verify free space, current control, artifact digests, source integrity, and
   that no unrecorded generation is active.
5. Snapshot or reflink the source generation and legacy `state.json` into
   `backups/<migration_id>/` with checksums.
6. Clone the source into a new, inactive
   `instances/<target_generation>/data/` staging tree.
7. Start only the target bundle against staging; execute health, DB verify,
   project inventory, and project smoke.
8. Migrate legacy `design_*` records through OpenDesign APIs, never direct
   SQLite writes.
9. Copy approved legacy imports through authorized OpenDesign file/upload
   routes, never browser-provided host paths.
10. Persist `legacy-project-map.json`, errors, checksums, and the `prepared`
    journal; fsync all of them.
11. Atomically replace `control.json` with target as `active` and source as
    `previous`, then fsync the directory.
12. Mark the journal `cutover_committed`, release the lock, and start the
    sidecar from the just-read active triple.

The cutover operation changes bundle and data together because they share one
JSON object and one atomic replace. There is no intermediate control state with
the new bundle and old data or vice versa.

## Crash recovery

Recovery first obtains the same migration lock, cleans only strictly named
regular stale control temp files, reads `control.json`, validates both artifact
and data references, and compares the relevant journal source and target to the
active triple. It never chooses a directory by age or lexical order.

| Crash point | Durable state that may exist | Recovery decision |
|---|---|---|
| Before staging or journal fsync | old control only | Keep old triple; discard incomplete staging only after bounded verification. |
| After `prepared` journal, before control temp fsync | old control + prepared journal | Keep old triple; report resumable/abortable prepared migration. |
| After control temp fsync, before `replace` | old control + complete temp + prepared journal | Keep old triple; remove the strictly named stale temp. |
| During atomic `replace` | old or new complete control | Validate the complete control observed; never merge fields. |
| After `replace`, before directory fsync | old or new complete control after crash | Validate the control observed and reconcile against journal source/target. |
| After directory fsync, before journal commit | new control + prepared journal | Keep new triple; finish journal transition to `cutover_committed`. |
| After journal commit | new control + committed journal | Start new triple after health verification. |

An invalid, missing, unknown, unverified, or journal-inconsistent reference is a
fail-closed recovery error. The launcher does not fall back to another
generation. A human-readable operator diagnostic may name IDs and status but
must not expose data contents or credentials.

## Rollback

Rollback is allowed only while the previous artifact and previous generation
remain intact and verified:

1. Freeze mutating operations and stop the current sidecar.
2. Re-read control and verify the retained `previous` triple and its snapshot.
3. Create and fsync a new rollback journal with current active as source and
   retained previous as target.
4. Atomically write a control record whose `active` is the retained previous
   triple and whose `previous` is the forward triple.
5. Mark the rollback journal committed.
6. Start the older bundle only on its original older data generation and run
   health/project smoke.

The forward-migrated data is never opened by the older bundle and is not
deleted by rollback. A "bundle-only rollback" is invalid.

## Retention

The default minimum retention is one complete previous bundle/data triple plus
the migration snapshot and journal. Operators may configure a larger count or
time window, never a smaller post-cutover guarantee. Cleanup is allowed only
when:

- no `active` or `previous` control field references the generation;
- no prepared or committed migration/rollback journal still needs it;
- the configured count and time window have expired;
- the active sidecar and migration lock prove the generation is unused;
- integrity and rollback policy checks pass.

Cleanup is an explicit app operation and is not performed by sidecar startup.

## Legacy catalog cutover

The existing Design Studio `state.json` becomes read-only legacy archive after
successful cutover. `legacy-project-map.json` maps each `design_*` id to one real
OpenDesign project id and records source checksum and migration id. New writes
go only through OpenDesign APIs. There is no second writable project catalog,
and canonical new references use the OpenDesign id.

## Security properties

- All tests and migrations use fixture or controlled-copy roots; no real
  workspace data is mutated by this gate.
- Control and generation roots reject symlinks and path traversal.
- Only verified artifact digests may appear in active or previous triples.
- Atomic write files are mode `0600` and are created in the destination
  directory with exclusive, no-follow semantics where supported.
- A crash cannot authorize a mixed bundle/data pair.
- Recovery fails closed and never starts an older bundle on forward data.
- The launcher does not build artifacts, apply migrations, or select newest
  data at startup.

## Executable proof

```bash
.venv/bin/python -W error::ResourceWarning -m unittest \
  tests.architecture.test_design_studio_data_generation_proof -v
```

The proof uses temporary fixture generations and injects failures immediately
before `replace` and immediately after it. It verifies atomic cutover and
rollback, immutable old/forward bytes, strict stale-temp recovery, selection
only from control in the presence of a newer inactive generation, artifact and
generation validation, and symlink rejection.

Expected result: nine passing tests, no resource warning.

## Consequences and follow-up

- G4 freezes the format and supplies the safe atomic control implementation; it
  does not migrate data.
- WP5 materializes and verifies immutable artifacts in digest-named registry
  directories. The launcher now resolves the bundle and data directory only
  from the validated active triple.
- WP6 uses the strict journal/control primitives to implement staging, API
  migration, legacy mapping, crash reconciliation, rollback, and retention
  cleanup on fixture copies.
- WP10 repeats migration, crash, and rollback scenarios through the final
  sidecar and UI topology.

Residual risk until WP6: no real workspace is authorized for migration, and a
fresh installation has no active generation until the controlled migration or
bootstrap operation writes a fully verified `control.json`. The launcher fails
closed in either state.
