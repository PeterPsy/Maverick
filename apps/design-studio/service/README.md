# Design Studio OpenDesign Service

This directory owns the external hosting and bridge code for the unchanged
official OpenDesign installation exposed as Maverick `app_id: design-studio`.
It does not contain an OpenDesign fork or an active custom UI/runtime build.

## Active runtime

`opendesign_official_release.json` pins the official
`ghcr.io/nexu-io/od:0.16.1` OCI manifest. `official_opendesign_release.py`
verifies the OCI identity, installs its unmodified layers, records an external
rootfs snapshot, and verifies every installed byte before activation.

`opendesign_launcher.py` is the thin sidecar entrypoint. Core mounts the
verified rootfs read-only, mounts only the workspace-scoped
`data/design-studio/opendesign-native/` data volume writable, and provides the
authenticated Unix relay and isolated browser origin. The launcher invokes the
official upstream entrypoint and never patches, overlays, injects, or
intercepts OpenDesign routes.

## External bridges

The Model Access Bridge consists of `model_access_client.py`,
`model_access_server.py`, `model_access_profiles.py`, and the
`maverick-codex` technical wrapper. It exposes configured API and CLI models
through protocols supported by OpenDesign without a Maverick runtime session,
prompt, memory, persona, skill, tool catalog, or semantic rewrite.

Delegation lives outside this service directory under `../backend/`. It calls
only supported native project, conversation, message, file, run, result, and
cancellation APIs and persists only bounded correlation metadata. Direct
native OpenDesign remains usable if either bridge is unavailable.

## One-time data cutover

`cutover_native_opendesign.py` drives the operator-controlled transition from
the retired customized generation to `opendesign-native/`:

1. require Core and every OpenDesign writer to be stopped;
2. verify the unchanged same-version official installation;
3. create a byte-verified immutable backup of canonical and legacy state;
4. run official migrations on disposable restored copies with both bridges
   disabled;
5. inventory projects, conversations, ordered messages, Design Systems, files,
   artifacts, settings, and run references only through supported HTTP APIs;
6. require identical redaction-safe category hashes;
7. atomically select the migrated native directory and freeze retired writer
   state; and
8. close legacy rollback before Core starts, then record native readiness.

The implementation is split by responsibility:

- `native_cutover_files.py`: safe copies, hashes, fsync, and read-only state;
- `native_cutover_state.py`: strict legacy paths, lock, and activation marker;
- `native_data_cutover.py`: backup/certification/atomic selection orchestration;
- `official_inventory_process.py`: disposable unchanged process and bounded
  public HTTP client;
- `official_inventory_values.py`: stable redaction-safe API normalization; and
- `official_public_inventory.py`: canonical public-surface inventory.

Neither cutover nor normal hosting imports a private OpenDesign database
driver. The immutable recovery backup necessarily retains canonical bytes;
Maverick's live cutover marker and certification summary retain only technical
identity, counts, and SHA-256 evidence.

## Focused verification

```bash
python3 -m unittest -v \
  apps/design-studio/tests/test_official_opendesign_release.py \
  apps/design-studio/tests/test_native_thin_host.py \
  apps/design-studio/tests/test_model_access_bridge.py \
  apps/design-studio/tests/test_native_delegation.py \
  apps/design-studio/tests/test_native_data_cutover.py \
  apps/design-studio/tests/test_official_public_inventory.py
```

The real disposable proof remains:

```bash
python3 apps/design-studio/service/smoke_official_opendesign.py \
  --installation /path/to/opendesign/official/<manifest-digest>
```
