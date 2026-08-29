# Design Studio OpenDesign Service

This directory owns the external hosting and bridge code for the unchanged
official OpenDesign installation exposed as Maverick `app_id: design-studio`.
It does not contain an OpenDesign fork or an active custom UI/runtime build.

## Active runtime

`opendesign_official_release.json` pins the initial official
`ghcr.io/nexu-io/od:0.16.1` OCI manifest. `official_opendesign_release.py`
verifies the OCI identity, installs its unmodified layers, records an external
rootfs snapshot, and verifies every installed byte before activation.

`opendesign_launcher.py` is the thin sidecar entrypoint. Core mounts the
platform artifact namespace read-only, mounts only the workspace-scoped
`data/design-studio/opendesign-native/` data volume writable, and provides the
authenticated Unix relay and isolated browser origin. The launcher resolves
the workspace's digest-protected release selection and directly invokes that
rootfs's unchanged loader, Tini, Node binary, and upstream daemon entrypoint.
It never patches, overlays, injects, or intercepts OpenDesign routes.
`official_process_supervisor.py` remains outside the product process: it
forwards lifecycle signals, checks the upstream `/api/ready` endpoint, and
keeps the redaction-safe host diagnostic synchronized even when both optional
bridges are disabled.

## Official release updates

`official_release_selection.py` owns the workspace-scoped official descriptor
selection. `native_official_update.py` verifies and installs a user-selected
official lock, stops only the managed Design Studio writer, creates an
immutable backup, runs upstream migration and public inventory on copies,
requires the migrated identity multiset and field-level user-content claims to
preserve every baseline item and value while permitting additive schema and
server-metadata evolution,
atomically swaps data and selection, and restores both if native readiness
fails. If the previous writer cannot be resumed, it remains fail-closed behind
quiescence with an explicit `recovery_required` marker.
`official_update_state.py` persists only release identities, category
counts/hashes, redaction-safe preservation counts, bridge states, and recovery
phase.

`official_bridge_contracts.py` exercises project, conversation, message, file,
run, cancellation, result, and status APIs on a disposable migrated copy. A
failure records delegation as degraded. The launcher independently checks the
Model Access Bridge after startup. Neither outcome gates native readiness.

## External bridges

The Model Access Bridge consists of `model_access_client.py`,
`model_access_server.py`, `model_access_profiles.py`, and the
`maverick-codex` and `maverick-opencode` technical wrappers. The install hook
attempts to install a digest-pinned OpenCode runtime; registry or verification
failure degrades only the API profile and never blocks native activation. The
launcher emits whichever supported Codex and OpenCode profiles are independently
usable plus a credential-free OpenCode provider configuration. This makes every
Core-granted API model visible in the native selector without manual provider
setup when the optional runtime is available, while a missing API or CLI catalog
does not remove the other profile. Both paths operate without a Maverick runtime
session, prompt, memory, persona, skill, tool catalog, or semantic rewrite.
The official daemon finds the production wrappers on Core's `/app/service`
mount, and both wrappers execute with `/usr/bin/python3`; `/maverick/python` is
reserved for artifact-root sidecars and is not part of this contract.

Delegation lives outside this service directory under `../backend/`. It calls
only supported native project, conversation, message, file, run, result, and
cancellation APIs and persists only bounded correlation metadata. A canonical
request fingerprint rejects conflicting idempotency-key reuse, a heartbeat
retains ownership during slow native calls, and a durable pre-POST submission
fence prevents a second run when the first response is uncertain. Direct native
OpenDesign remains usable if either bridge is unavailable.

## One-time data cutover

`cutover_native_opendesign.py` drives the operator-controlled transition from
the retired customized generation to `opendesign-native/`:

1. install a fail-closed relaunch gate and stop the managed OpenDesign writer;
2. verify the unchanged same-version official installation;
3. create a byte-verified immutable backup of canonical and legacy state;
4. run official migrations on disposable restored copies with both bridges
   disabled;
5. inventory projects, conversations, ordered messages, Design Systems, files,
   artifacts, settings, and run references only through supported HTTP APIs;
6. require identical redaction-safe category hashes;
7. atomically select the migrated native directory and freeze retired writer
   state; and
8. close legacy rollback, release the gate, synchronously prewarm through
   Core, and record native readiness.

The implementation is split by responsibility:

- `native_cutover_files.py`: safe copies, hashes, fsync, and read-only state;
- `native_cutover_state.py`: strict legacy paths, lock, and activation marker;
- `native_cutover_quiescence.py`: the fail-closed relaunch gate;
- `native_data_cutover.py`: backup/certification/atomic selection orchestration;
- `official_inventory_process.py`: disposable unchanged process and bounded
  public HTTP client;
- `official_inventory_values.py`: stable redaction-safe API normalization; and
- `official_public_inventory.py`: canonical public-surface inventory.

Neither cutover nor normal hosting imports a private OpenDesign database
driver. The immutable recovery backup necessarily retains canonical bytes;
Maverick's live cutover marker and certification summary retain only technical
identity, counts, and SHA-256 evidence.

## Verification

The maintained release gate runs the complete Design Studio Python suite,
frontend tests/build, the unchanged-official-package smoke, and two real E2E
proofs. A disposable unchanged daemon runs in a faithful bubblewrap filesystem
with `/app`, `/artifacts`, and `/model-access`, executes the production API and
CLI wrappers, proves OpenCode streaming/cancellation, reopens a delegated
conversation through the direct native API after restart, and verifies data,
delegation stores, assets, model catalogs, and capability credentials remain
isolated between two workspaces. Playwright then
drives the actual Base Shell frame host and Design Studio host through an exact
conversation deep link into a cross-origin native iframe. Focused, affected,
migration, and hosted profiles use the same runner:

```bash
npm --prefix apps/design-studio run test:e2e
npm --prefix apps/design-studio run test:e2e:migration
```

Individual focused checks remain available:

```bash
python3 -m unittest -v \
  apps/design-studio/tests/test_official_opendesign_release.py \
  apps/design-studio/tests/test_native_thin_host.py \
  apps/design-studio/tests/test_model_access_bridge.py \
  apps/design-studio/tests/test_native_delegation.py \
  apps/design-studio/tests/test_native_data_cutover.py \
  apps/design-studio/tests/test_native_cutover_quiescence.py \
  apps/design-studio/tests/test_official_public_inventory.py \
  apps/design-studio/tests/test_official_updates.py
```

The real disposable proof remains:

```bash
python3 apps/design-studio/service/smoke_official_opendesign.py \
  --installation /path/to/opendesign/official/<manifest-digest>
```
