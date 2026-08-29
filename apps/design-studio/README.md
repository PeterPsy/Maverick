# Design Studio

Design Studio is the Maverick host identity for an unchanged official
[OpenDesign](https://github.com/nexu-io/open-design) installation. It is not a
fork, overlay, or replacement editor.

## Native product boundary

The initial release is `ghcr.io/nexu-io/od:0.16.1`, pinned by manifest digest
in `service/opendesign_official_release.json`. The install hook verifies and
materializes the official OCI root filesystem in the platform artifact store.
Core mounts that store read-only; the thin launcher directly executes the
selected release's own musl loader, Tini, Node binary, and daemon entrypoint.
No version-specific root filesystem is baked into the app contract.

OpenDesign owns its UI, routes, projects, conversations, prompts, tools,
settings, migrations, and update behavior. Its persistent data lives at:

```text
workspaces/<workspace_id>/data/design-studio/opendesign-native/
```

The Maverick frontend only obtains a one-shot isolated-browser ticket and hosts
the native page in an iframe. Native HTTP routes pass through unchanged; no
normal OpenDesign request is handled by Core.

## Optional naked-model bridge

The sidecar requests the optional `services.http_sidecars[].model_access`
capability with API access and the installed `codex` CLI provider. Failure of
this capability never prevents OpenDesign from starting.

Core exposes a private, capability-authenticated Unix socket only inside the
sidecar. Raw provider credentials remain in Core Secrets and are never written
to OpenDesign data or injected into the sidecar environment. The launcher
provides two native integration forms and registers both in the supported
native OpenDesign profile file:

- an OpenAI-compatible endpoint at `http://127.0.0.1:49491/v1`, using the
  non-secret local handle `maverick-local`; and
- a local agent profile named `installed-codex-cli`, based on the upstream
  `codex` adapter and the technical wrapper `service/maverick-codex`; and
- a local agent profile named `installed-maverick-api`, based on the upstream
`opencode` adapter. Its generated OpenCode provider configuration exposes
every API model granted by Core under the `maverick/` provider namespace.

The unchanged daemon resolves both technical wrappers from `/app/service`, the
read-only app mount defined by Core for this sidecar type. The wrappers use the
minimal `/usr/bin/python3` runtime supplied by the sandbox; they never depend on
the artifact-root-only `/maverick/python` layout.

The install/upgrade hook also attempts to materialize a separately
digest-pinned official OpenCode technical runtime. `service/maverick-opencode`
invokes only that verified runtime. Consequently, granted API models appear in
OpenDesign's native selector on a fresh or upgraded installation without asking
the user to add an API provider manually. Download or verification failure is
reported as an API-profile degradation and never blocks native OpenDesign; the
Codex profile remains active. Conversely, an absent Codex catalog does not
remove a usable API profile.

The API bridge validates the selected configured model, forwards the exact
OpenDesign-authored JSON body, and streams the provider response. The CLI
bridge forwards the native adapter's argv, cwd, stdin, stdout, stderr, exit,
and cancellation semantics to a separately sandboxed Codex process. It does
not create a Maverick runtime session and does not add Maverick prompts,
memory, Chat history, personas, skills, tools, planning, or model substitution.

Profile and provider metadata is written only below OpenDesign's sandbox agent
home. It contains the loopback endpoint and non-secret local handle, but no
provider credential or semantic content. Users can still configure additional
providers through OpenDesign's own settings.

Redaction-safe bridge readiness and endpoint metadata are written to
`data/design-studio/bridge-capabilities.json`. Native operation remains
available when that file reports a degraded or disabled bridge.

## Official updates

An administrator selects a digest-locked official OCI release descriptor from
the workspace and applies it with the dedicated CLI surface:

```bash
maverick app design-studio cli run design-studio-update --action status --json
maverick app design-studio cli run design-studio-update \
  --action apply \
  --release-descriptor storage/uploaded/opendesign-release.json \
  --confirm true --json
```

The descriptor must name the official source repository and
`ghcr.io/nexu-io/od`, contain empty customizations, and lock the index,
platform manifest, config, every layer, provenance attestation, source commit,
and supported upstream runtime contract. Maverick installs and snapshots those
unchanged bytes under their manifest digest. The workspace selection in
`official-release-selection.json` is itself digest-protected.

Update activation briefly quiesces only the Design Studio sidecar. It creates
an immutable full data backup, inventories the current release through public
APIs, runs the candidate's supported upstream migration against a private
copy, inventories the migrated copy, and exercises the public delegation
contract on another disposable copy. Activation is permitted only when the
redaction-safe identity and field-level user-content claims prove that every
pre-migration project, conversation, ordered message, Design System, file,
artifact, setting, and run reference survives. New schema fields, normalized
server metadata, and updated bundled Design Systems are allowed; identity loss
or mutation/deletion of an existing user value fails before the active data or
release selection changes. Only then does the updater atomically select the
migrated data and release descriptor and prewarm the candidate.

Failure to start restores the complete prior data and release selection. If
that previous writer cannot itself be restarted—or its prewarm call raises—the
updater re-establishes quiescence, stops it again, and records
`recovery_required` instead of reporting a safe rollback. A model or delegation capability mismatch is recorded as degraded
and never rolls back or stops native OpenDesign.

## External delegation bridge

Maverick agents delegate through the backend/CLI/MCP entrypoints as external
clients of supported public OpenDesign APIs. One call selects or creates a
native project and conversation, uploads only explicitly authorized
attachments, appends exactly one ordinary visible message headed `Brief
delegated by Maverick`, and starts one native OpenDesign run. OpenDesign alone
selects and launches the requested naked agent/model.

The caller supplies a workspace-scoped idempotency key. The bridge binds that
key to a canonical fingerprint of the brief, target, model, reasoning option,
and ordered attachment identities; reuse with different inputs is rejected.
Deterministic message and assistant-message ids plus a continuously renewed
operation lease make concurrent retries safe. Before the non-idempotent run
POST, a durable submission fence is written. A response-loss retry recovers
the canonical `runId` from the native assistant message and never repeats an
uncertain POST. A disconnected caller does not cancel the OpenDesign run.

Maverick persists only the delegation id/status, canonical native ids, event
cursor, display-safe result references, exact conversation deep link, and
technical timestamps. It never persists the brief, transcript, attachment
body, artifact body/manifest, model request, process details, or a parallel
project catalog. Delegation unavailability does not affect direct use of the
native product.

## Host-owned surfaces

Maverick keeps only:

- official release verification and process lifecycle;
- workspace binding, authentication, isolated browser origin, and readiness;
- the optional technical Model Access Bridge;
- the external Delegation Bridge and bounded correlation state; and
- display-safe project references and explicit authorized delegation inputs.

## One-time native data cutover

Existing workspaces created by the retired customized runtime are moved once
from the active legacy generation into `opendesign-native/`. The operator
command `service/cutover_native_opendesign.py` first installs a fail-closed
quiescence marker and asks the live Core manager to stop the OpenDesign writer.
Any concurrent relaunch sees that marker and exits before opening native data.

`prepare` creates an immutable backup of the canonical OpenDesign directory,
the previous native directory, and the explicit legacy correlation/config
files. It restores two disposable copies, runs the unchanged same-version
official package with both bridges disabled, and compares redaction-safe
hashes for projects, conversations, ordered messages, Design Systems, project
files, artifacts, settings, and run references using only public APIs. It then
atomically selects the certified copy, removes only Maverick runtime metadata,
and makes the retired generation and writer state read-only.

Activation is explicit and ordered:

```bash
python3 apps/design-studio/service/cutover_native_opendesign.py prepare \
  --data-root /path/to/workspace/data/design-studio \
  --installation /path/to/artifacts/opendesign/official/<digest> \
  --confirm-writers-stopped
python3 apps/design-studio/service/cutover_native_opendesign.py activate \
  --data-root /path/to/workspace/data/design-studio \
  --cutover-id <reported-cutover-id> \
  --confirm-writers-stopped
# `activate` closes legacy rollback and synchronously prewarms native OpenDesign.
# Verify native readiness and the public inventory. If an offline recovery
# requires an explicit readiness record instead, use:
python3 apps/design-studio/service/cutover_native_opendesign.py finalize \
  --data-root /path/to/workspace/data/design-studio \
  --cutover-id <reported-cutover-id> --ready
```

`activate` closes rollback to the legacy writer before releasing quiescence and
synchronously starting the native sidecar through Core. A failed native
readiness check records `activation_failed` but never re-enables the legacy
writer. Backups and certification records contain recovery bytes or
category hashes as appropriate; the live Maverick marker contains no project,
transcript, file, artifact, or settings bodies.

The CLI and MCP surfaces must use supported public OpenDesign APIs. They must
never patch the official package, automate the browser, or read/write the
OpenDesign database directly.

## SDK Flow

The app SDK resolves the workspace-scoped Design Studio backend, CLI, MCP, and
reference surfaces declared by `app_contract.json`. Those surfaces are thin
external clients of the supported native OpenDesign project, conversation,
message, run-status, result, and cancellation APIs. They may keep bounded
delegation correlation and display-only view state, but never a second project
catalog or transcript. Browser traffic uses the isolated sidecar origin and
passes directly to the same official OpenDesign daemon.

## Contract Notes

The contract deliberately denies Maverick runtime-session creation and direct
secret delivery. Its provider permission authorizes only the scoped Model
Access Bridge; sidecar route policy remains pass-through. Attachment bytes must
be obtained through their owning authorized app surface and are handed directly
to OpenDesign without entering delegation state. Project references and view
state are resolved through public OpenDesign APIs.

## Verification

Focused checks:

```bash
python3 -m unittest \
  apps.design-studio.tests.test_official_opendesign_release \
  apps.design-studio.tests.test_native_thin_host \
  apps.design-studio.tests.test_model_access_bridge \
  apps.design-studio.tests.test_native_delegation \
  apps.design-studio.tests.test_native_data_cutover \
  apps.design-studio.tests.test_native_cutover_quiescence \
  apps.design-studio.tests.test_official_public_inventory \
  apps.design-studio.tests.test_official_updates \
  tests.unit.app_hosting.test_model_access_broker
```

Maintained aggregate gates (quick, affected, migration, hosted, and release)
are exposed through the package scripts. The release gate is the default and
adds real native selector, OpenCode streaming/cancellation, delegated
continuation, workspace-isolation, and browser deep-link proofs:

```bash
npm --prefix apps/design-studio run test:e2e
```

The official-package smoke remains valid with both bridges disabled:

```bash
python3 apps/design-studio/service/smoke_official_opendesign.py \
  --installation /path/to/official/<digest>
```
