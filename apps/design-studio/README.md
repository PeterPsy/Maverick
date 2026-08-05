# Design Studio

Design Studio is a Maverick app for bringing OpenDesign-style UI design workflows into a sandbox-first workspace.

It owns:

- a workspace frontend at `frontend/dist`
- a JSON backend at `backend/app_backend.py`
- CLI and MCP surfaces for project state, Storage import, and Storage export
- lifecycle hooks for app data setup and health checks
- a governed HTTP sidecar declaration under `services.http_sidecars`
- app data under `workspaces/<workspace_id>/data/design-studio/`

## OpenDesign Integration

The app contract is shaped for upstream `nexu-io/open-design` tag
`open-design-v0.16.1`, commit
`276b4d8e970bc143d7ad060181a89a834e3d9caf`.

Design Studio starts `service/opendesign_launcher.py` as the declared sidecar
command. `control.json` selects one indivisible artifact/version/data-generation
triple. The artifact digest resolves an immutable bundle below
`service/vendor/open-design/<artifact-sha256>/`; the data generation resolves
the only directory exported to OpenDesign as `OD_DATA_DIR`. A successful launch
writes redaction-safe status under
`data/design-studio/opendesign/launcher-status.json` and records
`mode: oci-musl-runtime`.

The primary distribution recipe is declared in
`service/opendesign_bundle.json` and implemented by
`service/import_opendesign_oci.py`. It imports the official pinned
`ghcr.io/nexu-io/od:0.16.1` linux/amd64 image directly over bounded HTTPS,
verifies the complete OCI descriptor chain and SLSA subject, and reconstructs
the layers without Docker. Two independent imports receive only the
digest-bound compiled loopback-bearer patch and stage the image's own musl
loader, Node 24 runtime, daemon, static web export and required native modules.
The two deterministic archives and all metadata must be byte-identical.
Runtime startup never installs dependencies, invokes a package manager, mounts
host Node, or builds Next.

The complete upstream web and daemon suites are a separate acceptance run via
`service/certify_opendesign_upstream.py`. They run once each with one worker on
adequate capacity; the packager never expands them into per-file processes,
checkpoints, retries, or memory-wait loops.

The generated OS/architecture artifact and its file manifest, CycloneDX SBOM,
license inventory, NOTICE, signed provenance, signature, and public key live
under ignored `service/artifacts/`. Their names, sizes, and SHA-256 digests are
pinned in the committed canonical manifest. `materialize_opendesign.py`
verifies every asset and the provenance signature before atomically installing
the closure in its digest-named registry directory. An existing digest
directory is immutable and is never overwritten after a verification failure.
The launcher revalidates every materialized file before each start.

Fresh checkouts will not include the materialized OCI bundle. Import the pinned
release assets before declaring the release complete:

```bash
python3 apps/design-studio/service/import_opendesign_oci.py \
  --signing-key /secure/path/opendesign-provenance-key.pem
python3 apps/design-studio/service/materialize_opendesign.py
python3 apps/design-studio/service/bootstrap_opendesign_generation.py \
  --data-root /path/to/new-empty-design-studio-data/opendesign
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
```

The explicit bootstrap command is only for a new empty data root. It refuses
legacy or unknown content; existing data must use the controlled migration and
is never migrated at launcher startup. The launcher fails closed when the
bundle, control record, or generation is absent or inconsistent. There is no
runtime compatibility fallback.

The upstream tag and official OCI image were inventoried before implementation.
The source tree includes web,
daemon, desktop, deploy, Helm/chart, design-system, skill, and plugin trees; the
daemon also has native dependencies including `node-pty`, `better-sqlite3`, and
`blake3-wasm`. The OCI closure loads the two modules needed on allowed routes;
the official image lacks a loadable linux `node-pty` binary and all terminal/
PTY routes stay denied. Vendoring
the full repository directly would mix sandbox-safe surfaces with full-access
surfaces the Maverick contract must keep blocked.

The production daemon replacement must preserve these boundaries:

- bind only to loopback
- derive `OD_DATA_DIR` only from the active controlled generation
- keep `OD_MEDIA_CONFIG_DIR` inside that same active generation
- receive only the technical `OD_API_TOKEN`
- run with `OD_SANDBOX_MODE=1`
- keep provider keys in Maverick/Vault-owned flows
- keep host folder import, terminal, and pty routes blocked in sandbox mode

## Storage Boundary

Design sources enter through Storage workspace-relative paths:

```text
storage/uploaded/<file>
storage/generated/<file>
```

Exports are written under:

```text
storage/generated/design-studio/<project-id>/<export-id>/
```

The app never accepts host absolute paths in sandbox mode. Hosted imports are
issued through the `storage-read` dependency backend request, then materialized
under `data/design-studio/imports/` only after Storage returns bounded file
content. Export writes are issued through Design Studio's `storage-write`
dependency backend request so the Storage app owns the generated file write path
and inventory update. Design Studio records imports and exports as pending first,
then marks them imported/exported or failed from the Storage callback result.
Direct local CLI/MCP test entrypoints may use the mounted workspace Storage roots
as a development fallback, but hosted backend calls use the declared Storage
dependencies.

## SDK Flow

Design Studio is a first-party source-available platform app under `apps/design-studio`, not a workspace-local SDK-generated app. It still follows the same contract validation and hosted lifecycle expectations:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
maverick app design-studio frontend build --json
maverick app design-studio cli list --json
maverick app design-studio mcp list --json
```

The app is installed into workspaces through the generic built-in app source registration and workspace binding flow. It must not be registered through app-specific bootstrap shortcuts.

## Contract Notes

The contract declares frontend, backend, CLI, MCP, lifecycle hooks, a bundled skill, referenceable `design_project` entities, standard view-state actions, Storage dependencies, and one app-owned HTTP sidecar.

The sidecar is sandbox-compatible because its mandatory generic
`process_policy` starts it under bubblewrap with an allowlisted environment,
read-only app bundle, writable validated app data root, isolated network
namespace, empty outbound list, resource/request limits, and an authenticated
Unix relay. Its loopback listener exists only inside that namespace; core never
publishes or falls back to a host TCP port. `HOME`, provider/runtime secrets,
cookies, Storage, operator paths, and other workspaces are absent. The generated
technical token uses the generic `${service.token}` substitution and is not the
relay capability.

The core sidecar proxy uses the ASGI streaming path for Design Studio routes. Request bodies are forwarded to the sidecar as chunks instead of through the JSON app-backend body limit, responses are streamed back to the browser, and SSE responses are preserved without exposing the generated `OD_API_TOKEN` to the client.

The sidecar also declares the generic isolated `browser_origin` capability.
Core, not Design Studio or OpenDesign, derives the opaque workspace/app/
generation host, issues the short-lived body-only bootstrap ticket, sets the
separate host-only session cookie, and applies the fixed
`self_hosted_web_app` CSP profile. Root-relative OpenDesign requests therefore
remain on the sidecar origin and never fall through to Maverick routes. Neither
Maverick cookies nor the generated `OD_API_TOKEN` cross the browser/upstream
boundary.

The browser route policy is generated from the pinned 0.16.1 method/template
inventory and checked in CI with `service/sync_route_policy.py`. API rules are
exact and segment-aware; unsafe allows name their method, dynamic parameters
consume one segment, and prefix/regex/splat escalation is rejected. Only
GET/HEAD static trees outside `/api` cover `/_next`, assets, artifacts, and
frames. Known terminal/PTY, host-folder, external-open, deploy, connector/OAuth,
plugin install/upload, persistent MCP, telemetry, and other inventoried routes
are blocked explicitly; all other routes are denied by default.

Backend, CLI, MCP, and reference access uses the separate generic
`entrypoint_access` contract. Each invocation receives an opaque, per-process
SDK capability for `GET /api/projects` and `GET /api/projects/{id}` only, with a
30-second TTL, request budget, explicit request/response limits, and no
streaming. `core.app_sdk.app_sidecar` calls the core-owned Unix broker; Design
Studio never learns the OpenDesign port, `OD_API_TOKEN`, relay capability, or
database path. The capability is bound to workspace, local app, service,
surface, actor, and invocation and is revoked when the entrypoint finishes.
Reference calls use their own GET-only policy and cannot inherit MCP mutation
authority. Broker failure has no loopback or filesystem fallback.

An explicit OpenDesign project id is resolved through this SDK path by the
backend (and therefore the mounted frontend), CLI `get_project`, MCP
`design_studio_get_project`, and the standard Design Studio reference
resolve/summarize tools. Legacy `design_*` records remain a read-only legacy
catalog until a separately authorized controlled migration maps them to real
OpenDesign ids; no OpenDesign data is read directly from `app.sqlite`.

The production confinement suite uses real bubblewrap and validates filesystem,
environment, network, authenticated relay, concurrency and descendant cleanup:

```bash
python3 -W error::ResourceWarning -m unittest \
  tests.integration.app_hosting.test_sidecar_execution \
  tests.integration.app_hosting.test_sidecar_browser_origin \
  tests.integration.app_hosting.test_sidecar_entrypoint_broker
```

Routes declared as `handled_by_core` are routed to the Design Studio backend with the `sidecar_core_handler` surface instead of reaching the OpenDesign sidecar. The implemented sandbox handlers cover:

- `GET /api/media/config`, returning sanitized Maverick-managed provider config without keys
- `POST /api/import/storage`, importing through the selected `storage-read` dependency backend
- `POST /api/export/storage`, exporting through the selected `storage-write` dependency backend
- `POST /api/provider/models`, mapping OpenDesign provider model discovery to the active Maverick workspace provider without forwarding provider routes to the sidecar

The contract declares `permissions.providers.model_proxy: true` with `credential_source: core-vault` and `deliver_secrets_to_app: false`. It does not declare app-scoped provider secret reads. Provider keys stay in Maverick/Vault-owned flows, are not delivered to the browser, Design Studio backend, or OpenDesign sidecar, and are not written into `OD_MEDIA_CONFIG_DIR`. Provider errors are returned in OpenDesign's provider-model response shape (`ok`, `kind`, `latencyMs`, `status`, `detail`) so the bundled UI can handle unavailable provider state without learning raw credentials.

## Verification

Useful checks:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
python3 -m unittest apps/design-studio/tests/test_opendesign_oci_import.py
python3 -m unittest apps/design-studio/tests/test_opendesign_materialization.py
python3 -m unittest apps/design-studio/tests/test_opendesign_migration.py
python3 apps/design-studio/service/sync_route_policy.py
python3 apps/design-studio/service/smoke_opendesign_runtime.py
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
maverick app design-studio frontend build --json
maverick app design-studio mcp list --json
maverick app design-studio cli list --json
```

Current intentional omissions:

- generated OpenDesign assets and dependency closures stay out of source control
- real workspace migration remains unauthorized; migration tests operate only on marked fixtures and controlled copies
- the source-build baseline remains a separate fallback certification; the primary OCI artifact is pinned and its real acceptance evidence is committed
- provider proxying is limited to OpenDesign model discovery through Maverick's active workspace provider; generation/chat provider routes remain unavailable in sandbox mode
- full-access terminal, Local CLI, and host-folder import are not part of the sandbox MVP
