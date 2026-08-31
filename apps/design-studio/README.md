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

Core exposes only that subtree as sidecar `/data` and uses the same subtree as
the writable Model Access CLI scope. A native Codex `--add-dir` may additionally
name an existing directory below the sidecar's declared `opendesign` artifact
namespace; Core bind-mounts only each exact requested directory read-only.
Release selection, quiescence, update journals, delegation metadata, and
immutable backups remain sibling host-control data and are never mounted into
OpenDesign or Codex.

The Maverick frontend obtains a one-shot isolated-browser ticket and a separate
Core confirmation token, then hosts the native page in an iframe. It declares
the native frame ready only after Core confirms that bootstrap produced the
bound sidecar session; `iframe.onload` alone is intentionally insufficient
because browsers also emit it for TLS/network error documents. Native HTTP
routes pass through unchanged; no normal OpenDesign request is handled by Core.
OpenDesign's native preview surface deliberately uses opaque-origin sandboxed
iframes. The app contract therefore opts only its plugin-asset tree and exact
asset-cache route into Core's sandbox-resource response policy, allowing those
authenticated images to render without changing the official OpenDesign
frontend. Core keeps the main session `SameSite=Strict` and accepts a separate
host-only resource cookie only for those declared preview-media `GET`/`HEAD`
routes; other sidecar responses retain the stricter resource policy.

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
and cancellation semantics to a separately sandboxed Codex process. Core—not
the sidecar-writable native profile—requires exactly one `--model` on every
non-diagnostic execution and authorizes it against the live catalog for the
lease's workspace/app scope before the executor starts. It does not create a
Maverick runtime session and does not add Maverick prompts, memory, Chat
history, personas, skills, tools, planning, or model substitution.

OpenDesign 0.21 also supplies a fixed Codex shell-environment policy block on
every native run. Core admits only that exact certified block, including its
closed `include_only` key list; an added key or altered value remains denied.
These argv overrides govern the already bounded executor environment and do
not create a general sidecar environment-delivery channel. The same release
passes its bundled `skills` and `design-systems` directories through
`--add-dir`; Core resolves those paths only beneath the declared, verified
artifact namespace and mounts the two requested directories read-only. Missing,
undeclared, non-directory, traversal, and symlink-escape paths fail closed.

Before Core publishes native readiness, the launcher reads OpenDesign's
supported `/api/app-config` surface. An unset selection, or
the upstream `amr` cloud selection that cannot run inside the credential-free
sidecar, is moved to the primary available Maverick native profile with
`PUT /api/app-config`. Explicit non-cloud user selections are preserved. This
prevents OpenDesign's cloud sign-in flow from hiding the locally integrated
product without modifying the official root filesystem or frontend.

Profile and provider metadata is written only below OpenDesign's sandbox agent
home. It contains the loopback endpoint and non-secret local handle, but no
provider credential or semantic content. Users can still configure additional
providers through OpenDesign's own settings.

The host-only launch preparation writes only the release-bound delegation
projection to `data/design-studio/bridge-capabilities.json`. Core separately
mounts one declared diagnostics file—not the surrounding app-data root—at
`/run/maverick/sidecar-status.json`. The thin launcher writes its real
lifecycle and Model Access result through that single-file capability, so
`native-host-status.json` cannot remain a stale prelaunch placeholder. Native
operation remains available when a bridge is degraded or disabled.

## Official updates

An administrator selects a digest-locked official OCI release descriptor from
the workspace and applies it with the dedicated CLI surface:

```bash
maverick app design-studio cli run design-studio-update --action status --json
maverick app design-studio cli run design-studio-update \
  --action recover --confirm true --json
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
pre-migration project, conversation, ordered message, user-owned Design
System, file, artifact, setting, and run reference survives. Functional
project metadata such as entry files, media configuration, templates, and
voice is protected. Project fields are discovered dynamically and protected
independently from both `/api/projects` list records and `/api/projects/:id`
details rather than selected by a positive list; only explicitly enumerated
volatile server fields and list-only run status are normalized away. Claims
also encode object/array presence and type, so deleting an empty functional
container is destructive.
New schema fields and updates, renames, or removals of
release-owned bundled Design Systems remain allowed. Identity loss or
mutation/deletion of an existing user value fails before the active data or
release selection changes. Only then does the updater atomically select the
migrated data and release descriptor.

The per-workspace update lock remains held through readiness or safe recovery.
A durable `preparing` marker is fsynced before quiescence, and an intent journal
is fsynced before each directory rename. Before quiescence is released or Core
can prewarm the selected candidate, the updater durably records the irreversible
`committed` decision with `native_ready: false`. A crash can therefore never
expose candidate writes and later restore an older backup over them. The live,
canonically bound prewarm then sets `native_ready: true` and records the real
launcher handshake. On the next managed launch, host preparation automatically
restores the prior selection and full backup for any pre-commit transaction, or
permits the committed candidate to resume without rollback. Because host
preparation precedes process spawn, it always leaves `native_ready: false`;
only a post-spawn, canonically bound prewarm may set it to true. The explicit
`recover` action performs that verification and restarts the writer. Disposable
migration, inventory, smoke, and delegation probes run without a network
interface; their public API is reachable only through an authenticated local
Unix relay inside that namespace.

Failure before the commit decision restores the complete prior data and release
selection. Failure after that decision leaves the candidate selected and marks
it not ready; recovery retries that same candidate and never discards writes
that could have occurred after exposure. Every stop and readiness decision
requires Core evidence for the exact workspace id, app id, canonical data root,
declared `opendesign` service, and live/stopped instance state. If a pre-commit
stop cannot be proven, the updater first requires Core to persist a
workspace/app quarantine, revoke proxy and browser authority, revoke and cancel
model-access leases, and fence all relaunches; only then is
`recovery_required` recorded. The Core fence survives backend restart and
requires explicit operator release. A model or delegation capability mismatch
is recorded as degraded and never rolls back or stops native OpenDesign.

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

`activate` first verifies through Core that the requested workspace resolves to
the stopped, explicitly non-quarantined sidecar bound to the exact canonical
data root. A missing quarantine result fails closed. Only after that preflight
succeeds does it close rollback to the legacy writer, release quiescence, and
synchronously start the native sidecar. A failed post-preflight native
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
  tests.unit.app_hosting.test_model_access_broker \
  tests.unit.app_hosting.test_model_access_cli_sandbox \
  tests.integration.app_hosting.test_sidecar_execution
```

Maintained aggregate gates (quick, affected, migration, hosted, and release)
are exposed through the package scripts. The release gate is the default and
adds real native selector, API/CLI streaming and cancellation, tools/media at
the model boundary, delegated continuation, explicit cross-workspace denial,
and browser deep-link proofs:

```bash
npm --prefix apps/design-studio run test:e2e
```

The official-package smoke remains valid with both bridges disabled:

```bash
python3 apps/design-studio/service/smoke_official_opendesign.py \
  --installation /path/to/official/<digest>
```
