# Design Studio

Design Studio is the Maverick host identity for an unchanged official
[OpenDesign](https://github.com/nexu-io/open-design) installation. It is not a
fork, overlay, or replacement editor.

## Native product boundary

The selected release is `ghcr.io/nexu-io/od:0.16.1`, pinned by manifest digest
in `service/opendesign_official_release.json`. The install hook verifies and
materializes the official OCI root filesystem in the platform artifact store.
Core mounts that root filesystem read-only and starts its official entrypoint.

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
provides two native integration forms:

- an OpenAI-compatible endpoint at `http://127.0.0.1:49491/v1`, using the
  non-secret local handle `maverick-local`; and
- an OpenDesign local agent profile named `installed-codex-cli`, based on the
  upstream `codex` adapter and the technical wrapper `service/maverick-codex`.

The API bridge validates the selected configured model, forwards the exact
OpenDesign-authored JSON body, and streams the provider response. The CLI
bridge forwards the native adapter's argv, cwd, stdin, stdout, stderr, exit,
and cancellation semantics to a separately sandboxed Codex process. It does
not create a Maverick runtime session and does not add Maverick prompts,
memory, Chat history, personas, skills, tools, planning, or model substitution.

OpenDesign users configure the standard API endpoint through OpenDesign's own
provider settings. CLI model metadata is written only to the supported native
`OD_AGENT_PROFILES_CONFIG` file under OpenDesign's sandbox agent home; it
contains no credential or semantic content.

Redaction-safe bridge readiness and endpoint metadata are written to
`data/design-studio/bridge-capabilities.json`. Native operation remains
available when that file reports a degraded or disabled bridge.

## External delegation bridge

Maverick agents delegate through the backend/CLI/MCP entrypoints as external
clients of supported public OpenDesign APIs. One call selects or creates a
native project and conversation, uploads only explicitly authorized
attachments, appends exactly one ordinary visible message headed `Brief
delegated by Maverick`, and starts one native OpenDesign run. OpenDesign alone
selects and launches the requested naked agent/model.

The caller supplies a workspace-scoped idempotency key. Deterministic message
and assistant-message ids plus a short operation lease make concurrent and
response-loss retries safe: the bridge recovers the canonical `runId` from the
native assistant message rather than appending or starting again. A disconnected
caller does not cancel the OpenDesign run.

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
  tests.unit.app_hosting.test_model_access_broker
```

The official-package smoke remains valid with both bridges disabled:

```bash
python3 apps/design-studio/service/smoke_official_opendesign.py \
  --installation /path/to/official/<digest>
```
