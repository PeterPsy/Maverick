# Design Studio OpenDesign Launch Selections and Data Generations

Status: Historical (superseded 2026-08-28)

Superseded by
[`design_studio_native_opendesign_architecture.md`](design_studio_native_opendesign_architecture.md).
This document records the retired patched-artifact, web-overlay, and custom
generation-control model only. The active Design Studio host selects a
digest-locked unchanged official OpenDesign release and gives its upstream
migrations sole ownership of `opendesign-native/`; the control-v2 machinery
described below has been deleted and must not be reintroduced.

Former status: Accepted (schema v2 incremental cycle)

Date: 2026-08-12

## Scope

This ADR freezes coordinated OpenDesign runtime, web overlay, and data cutover,
crash recovery, retention, and rollback for Design Studio. OpenDesign
migrations are forward-only: an older runtime must never open a directory
already migrated by a newer runtime.

Migration implementation applies only to marked fixtures and controlled
copies. It does not authorize migration of a real workspace. Web-only
activation is separately authorized because it does not clone or migrate data.

## Decision

One app-owned `control.json` selects the active OpenDesign instance. Its
`active` object is an indivisible launch selection:

```text
(runtime_artifact_sha256, web_overlay_sha256, od_version, data_generation)
```

This is not the old runtime/version/data triple with an optional web digest.
Schema v2 also holds two independent complete rollback selections:

- `previous_release` retains the previous runtime/version/data/overlay;
- `previous_web` retains a compatible prior overlay by repeating the current
  runtime/version/data fields and changing only the web digest.

The control file is replaced atomically. A symlink, directory name,
modification time, manifest alone, or "newest" heuristic never selects an
instance. The launcher resolves the immutable runtime, immutable overlay, and
data directory from the validated selection and refuses to start if any
reference is missing, incompatible, or unverified.

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
web-activations/
  web_<id>.json
legacy-project-map.json
```

`instances/<generation>/data/` is the only directory passed as `OD_DATA_DIR`.
The generation directory and its `data/` child must be real directories below
the app data root; symlinks are rejected. Staging and previous generations are
not mounted into an active sidecar.

Runtime and web artifacts are immutable installation assets outside this
writable data tree. Runtime digests must be present in the verified runtime
registry and overlay digests in the verified web registry before a selection
can be parsed, written, activated, recovered, or rolled back.

## Control schema v2

The complete schema is:

```json
{
  "schema_version": "2",
  "active": {
    "runtime_artifact_sha256": "<lowercase sha256>",
    "web_overlay_sha256": "<lowercase sha256>",
    "od_version": "0.16.1",
    "data_generation": "gen_<id>"
  },
  "previous_release": {
    "runtime_artifact_sha256": "<lowercase sha256>",
    "web_overlay_sha256": "<lowercase sha256>",
    "od_version": "0.10.1",
    "data_generation": "gen_<id>"
  },
  "previous_web": null,
  "migration_id": "migration_<id>",
  "web_activation_id": null,
  "updated_at": "<RFC3339 with timezone>"
}
```

For the first bootstrapped generation, both rollback selections and both
journal ids may be null. A release cutover sets `previous_release` and
`migration_id`, clears `previous_web` and `web_activation_id`, and requires the
active and previous data generations to differ. A web-only cutover preserves
`previous_release` and `migration_id`, sets `previous_web` and
`web_activation_id`, and requires `active` and `previous_web` to have identical
runtime, version, and data fields but different overlay digests.

Unknown, duplicate, missing, malformed, oversized, non-UTF-8, or non-JSON input
is rejected. The parser verifies every referenced generation and artifact
before returning a usable control record.

Strict value objects live in
`apps/design-studio/service/opendesign_generation_model.py`; filesystem I/O
lives in `opendesign_generation_control.py`. Reads use no-follow regular-file
checks and bounded strict JSON. Writes use same-directory exclusive temporary
files, flush and `fsync`, atomic `replace`, and directory `fsync`.

## Migration journal

Release migration writes `migrations/<migration_id>.json` before changing
`control.json`. Its source and target are complete launch selections:

```json
{
  "schema_version": "2",
  "migration_id": "migration_<id>",
  "state": "prepared",
  "source": {"runtime_artifact_sha256": "<sha256>", "web_overlay_sha256": "<sha256>", "od_version": "0.10.1", "data_generation": "gen_old"},
  "target": {"runtime_artifact_sha256": "<sha256>", "web_overlay_sha256": "<sha256>", "od_version": "0.16.1", "data_generation": "gen_new"},
  "source_snapshot": "backups/migration_<id>",
  "checks": {},
  "created_at": "<RFC3339>",
  "updated_at": "<RFC3339>"
}
```

The state machine is `prepared -> cutover_committed` or
`prepared -> aborted`. Rollback creates a new journal. Journal writes use the
same atomic protocol as control. Migration journals are never edited by a
web-only activation. Records contain only redaction-safe inventory, checksums,
health, DB verification, and bounded errors.

## Cutover protocol (release)

Controlled migration executes this order on a marked fixture or copy:

1. Acquire the Design Studio migration lock and reject new mutations.
2. Wait for active runs or cancel them under declared policy.
3. Stop the active sidecar and prove the data root is unused.
4. Verify control, artifact digests, source integrity, and free space.
5. Snapshot the source generation and legacy state with checksums.
6. Clone source into a new inactive data generation.
7. Start only the target runtime/overlay against staging and run health, DB,
   inventory, and project smoke checks.
8. Migrate legacy records through OpenDesign APIs, never direct SQLite writes.
9. Copy approved imports through authorized OpenDesign routes.
10. Persist mapping, checks, and prepared journal; fsync all of them.
11. Atomically replace control with target as `active`, source as
    `previous_release`, and `previous_web` cleared.
12. Mark the journal committed, release the lock, and start from the just-read
    active selection.

Runtime, overlay, and data change together in one atomic object. There is no
intermediate state with a new runtime on old data, and a prior web selection
cannot cross a runtime/data boundary.

## Web-only activation journal and protocol

Web activation journals live at `web-activations/<web_activation_id>.json` and
contain strict `source` and `target` complete selections, state, readiness
evidence, timestamps, and redaction-safe failure data. The state machine is
`prepared -> ready_committed` or `prepared -> rolled_back`. Source and target
must differ only in `web_overlay_sha256`.

Activation executes this order:

1. Verify the target overlay, externally pinned signature trust root, complete
   file manifest, and compatibility with the active runtime, OpenDesign
   version, upstream pin, toolchain, and platform.
2. Write and fsync the `prepared` web activation journal.
3. Atomically replace control with target as `active` and source as
   `previous_web`. Preserve `previous_release`, `migration_id`, runtime digest,
   version, data generation, data bytes, and every migration journal.
4. Request the generic app/workspace-scoped sidecar restart and wait for its
   declared readiness.
5. On success, mark the web journal `ready_committed`.
6. On restart/readiness failure, atomically restore source as `active`, retain
   target as `previous_web`, restart source, and mark the journal `rolled_back`.
   If source readiness also fails, remain fail-closed and report both bounded
   errors.

No data generation is cloned, opened by a migration process, or rewritten by
this protocol. The migration id and journal bytes must remain unchanged.

## Crash recovery

Recovery obtains the relevant lock, removes only strictly named regular stale
temporary files, reads strict control, validates all references, and reconciles
the referenced journal. It never chooses a directory by age or lexical order.

| Crash point | Durable state | Recovery decision |
|---|---|---|
| Before journal fsync | old control | Keep old complete selection. |
| After prepared journal, before control replace | old control + prepared journal | Keep old selection and report prepared work. |
| After control temp fsync, before replace | old control + complete temp + journal | Keep old selection; remove only strict stale temp. |
| During replace | old or new complete control | Validate the complete control observed; never merge fields. |
| After replace, before directory fsync | old or new complete control | Reconcile only the complete selection observed. |
| After directory fsync, before journal commit | new control + prepared journal | Keep new release selection and commit migration journal; for web, run readiness and commit or auto-rollback. |
| After journal commit | matching control + committed journal | Start active selection after verification. |

For web recovery, source active plus a prepared journal means cutover did not
commit. Target active plus source in `previous_web` means readiness evidence is
incomplete; recovery runs readiness and either commits or automatically rolls
back. Ready-committed and rolled-back journals must exactly match control.
Recovery never copies data or changes a migration journal.

Invalid, missing, unknown, unverified, or journal-inconsistent references fail
closed. The launcher does not fall back to another generation or overlay.

## Rollback

Release rollback is allowed only while the previous runtime, overlay, data
generation, and snapshot remain intact and verified. It creates a new rollback
migration journal, atomically swaps `active` and `previous_release`, clears
`previous_web`, and starts the older runtime only on its original data. The
forward-migrated data is never opened by the older runtime or deleted. A
runtime-only rollback is invalid. In the earlier terminology, it is also never opened by the older bundle.

Web rollback uses the web-only protocol. It swaps only the overlay selection,
does not acquire migration authority, and does not mutate data or migration
journals.

## Retention

The default minimum retention is one complete previous release selection in
`previous_release`, with its runtime,
overlay, snapshot, and journal, plus one compatible `previous_web` overlay and
web activation journal. Cleanup is explicit and allowed only when no control or
journal reference needs an artifact/generation, retention windows have expired,
the sidecar and locks prove it unused, and integrity checks pass.

## Legacy catalog cutover

Legacy `state.json` is a read-only archive after migration.
`legacy-project-map.json` maps each old id to a real OpenDesign project id.
New writes use OpenDesign APIs; there is no second writable project catalog.

## Security properties

- Generation roots, control, journals, runtime artifacts, and overlays reject
  symlinks and path traversal.
- Only verified runtime and overlay digests appear in control selections.
- Overlay signature verification uses a trust root pinned outside the overlay.
- A crash cannot authorize a mixed runtime/overlay/data selection.
- The launcher does not build, migrate, choose newest, or use embedded web.
- Web activation never grants migration or data mutation authority.
- Evidence excludes cookies, provider keys, prompts, environment values, host
  paths, and secrets.

## Executable proof

```bash
python3 -W error::ResourceWarning -m unittest \
  apps/design-studio/tests/test_data_generation_proof.py \
  apps/design-studio/tests/test_opendesign_web_overlay.py -v
python3 apps/design-studio/service/smoke_opendesign_migration.py
```

The release product gate separately runs all fourteen browser scenarios in two
workspaces. Migration/rollback smoke is a separate gate rather than setup for
each UI test.

## Consequences

- The launcher resolves runtime, overlay, and data only from schema v2.
- The daemon requires `OD_STATIC_DIR` and has no embedded-web fallback.
- Web overlay development may use a single derivation and warm caches.
- Final release remains gated by two clean derivations and byte comparison.
- Real workspace migration remains unauthorized; a fresh installation has no
  active selection until controlled bootstrap writes verified control.
