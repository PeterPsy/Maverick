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
command. Control schema v2 selects one indivisible runtime artifact digest,
web overlay digest, OpenDesign version, and data generation. The runtime digest
resolves an immutable closure below
`service/vendor/open-design/<runtime-sha256>/`; the overlay digest resolves
verified static output below
`service/vendor/open-design-web/<web-sha256>/`; and the data generation resolves
the only directory exported as `OD_DATA_DIR`. The daemon requires the explicit
`OD_STATIC_DIR` selected from that verified overlay registry and has no embedded
web fallback. A successful launch writes both digests to the redaction-safe
status under
`data/design-studio/opendesign/launcher-status.json` and records
`mode: oci-musl-runtime`.

The primary distribution recipe is declared in
`service/opendesign_bundle.json` and implemented by
`service/import_opendesign_oci.py`. It imports the official pinned
`ghcr.io/nexu-io/od:0.16.1` linux/amd64 image directly over bounded HTTPS,
verifies the complete OCI descriptor chain and SLSA subject, and reconstructs
the layers without Docker. Runtime derivations apply only daemon/runtime
patches and stage the image's own musl loader, Node 24 runtime, daemon, and
required native modules; static web output is deliberately absent. The patch
series separately identifies `runtime`, `web-build`, and `web-react`
components, so React/CSS or web-build changes do not invalidate runtime inputs.
Two clean runtime derivations and, independently, two clean release-overlay
derivations must be byte-identical.
Runtime startup never installs dependencies, invokes a package manager, mounts
host Node, or builds Next.

The complete upstream web and daemon suites are a separate acceptance run via
`service/certify_opendesign_upstream.py`. They run once each with one worker on
adequate capacity; the packager never expands them into per-file processes,
checkpoints, retries, or memory-wait loops.

The generated OS/architecture runtime artifact and its file manifest,
CycloneDX SBOM, license inventory, NOTICE, signed provenance, signature, and
public key live under ignored `service/artifacts/`. Their names, sizes, and
SHA-256 digests are pinned in the committed canonical manifest.
`materialize_opendesign.py`
verifies every asset and the provenance signature before atomically installing
the closure in its digest-named registry directory. An existing digest
directory is immutable and is never overwritten after a verification failure.
The launcher revalidates every file in the exact bundle selected for execution
before each start. Retained rollback bundles are revalidated in full when a
controlled operation selects them; unrelated registry entries are never placed
on the execution path.

Each immutable web overlay carries a file-level manifest, archive digest,
runtime/upstream compatibility, lockfile and toolchain digests, CycloneDX SBOM,
licenses, provenance, and signature. Verification uses the separately reviewed
trust root pinned by `service/opendesign_web_trust.json`; a key delivered only
inside an overlay cannot authorize it. Materialization rejects traversal,
symlinks, path escape, incompatible selections, signature failure, or any
file-level mismatch before an atomic publish.

`service/opendesign_web_builder.py` keeps persistent dependency, invariant
workspace-output, source/build, and compatible Next caches. Entries carry
content manifests, use per-key locks, and publish by atomic rename. Dependency
identity includes the lockfile, package graph, Node, pnpm, and platform; a
valid entry skips `pnpm install --frozen-lockfile`. Development uses one
bounded Turbopack derivation and may reuse verified caches. A release disables
all of them for two clean independent derivations and a byte-for-byte
comparison.

Fresh checkouts will not include the materialized OCI bundle. Import the pinned
release assets before declaring the release complete:

```bash
python3 apps/design-studio/service/import_opendesign_oci.py \
  --source-repository /path/to/open-design-v0.16.1/.git \
  --signing-key /secure/path/opendesign-provenance-key.pem
python3 apps/design-studio/service/materialize_opendesign.py
python3 apps/design-studio/service/opendesign_web_release.py \
  --source-repository /path/to/open-design-v0.16.1/.git \
  --signing-key /secure/path/opendesign-provenance-key.pem
python3 apps/design-studio/service/bootstrap_opendesign_generation.py \
  --data-root /path/to/new-empty-design-studio-data/opendesign
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
```

For the one-time v1 rollout, pass the currently active v1 runtime digest once
with `--compatible-runtime-artifact-sha256`; the canonical overlay will then be
valid for both the source and the new `OD_STATIC_DIR` runtime. Later overlays
default to the runtime digest pinned by the current manifest.

The explicit bootstrap command is only for a new empty data root. It refuses
legacy or unknown content; existing data must use the controlled migration and
is never migrated at launcher startup. The launcher fails closed when the
bundle, control record, or generation is absent or inconsistent. There is no
runtime compatibility fallback.

The one-time v1-to-v2 rollout publishes the sole new runtime requiring
`OD_STATIC_DIR` together with the canonical overlay, converts the existing
control record atomically, and executes a controlled runtime cutover. After
that cutover, React/CSS changes use only overlay build, materialization, and
web activation. A web-only activation changes only
`active.web_overlay_sha256` and
`previous_web`: it does not clone data, run migrations, change the runtime
digest, or touch the migration journal. Restart/readiness failure restores the
previous compatible overlay automatically. A later selected gate failure also
restores that overlay before `dev apply` reports failure. Every new cutover
first completes any pending activation recovery; backend restart dispatches the
app-owned `backend_recovery` hook so a rollback already committed before the
restart reaches its terminal journal state.

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
storage/generated/design-studio/<od-project-id>/<od-run-id>/
```

The app never accepts host absolute paths in sandbox mode. Hosted imports are
issued through the `storage-read` dependency backend request. Core gives the
result callback a fresh backend-scoped sidecar capability; the callback uploads
the bounded bytes through `POST /api/projects/{id}/files` and verifies a raw
read-back SHA-256 before marking the import complete. Design Studio never keeps
a second copy under app data.

Exports require a terminal canonical `od_run_id`. Design Studio reads the real
OpenDesign file catalog, obtains the project file archive from the governed
batch archive API, and writes `project-files.zip`, `result-package.json`, and
`manifest.json` through `storage-write`. The manifest records SHA-256, size,
media type, the OpenDesign run id, Maverick runtime correlation ids, OCI pin,
materialized artifact digest, and Storage-import provenance. Storage owns every
generated file and inventory update.

`data/design-studio/adapter-state.json` contains only view state and bounded
import/export job metadata. OpenDesign remains the sole owner of projects,
conversations, runs, and project files. The migrated `state.json` is a sealed
legacy archive; `design_*` is accepted only as an input alias resolved through
`opendesign/legacy-project-map.json`, and canonical responses always return
`od_project_id` with an optional `legacy_project_id`.

## Frontend Boundary

The Maverick frontend is a full-bleed host for the native OpenDesign editor. A
`shell.sidebar.primary` widget renders the canonical OpenDesign project catalog
with search, recent ordering, loading/error/empty states, and selected-project
state; its fixed footer creates a canonical project. The widgets call the
Design Studio backend and never persist a duplicate catalog. Their layout uses
the shell-owned `is_mobile_layout` context rather than iframe media queries.

The editor host requests a one-shot launch from
`POST /api/app-sidecars/browser-launch`, validates that the response names a
different HTTP origin and the exact clean bootstrap endpoint, and submits the
ticket through a transient form POST targeted at the iframe. The ticket is
cleared from the form immediately and is never put in a URL, fragment,
localStorage, log, or persisted React state.

After the `303`, the OpenDesign UI and all of its API requests stay same-origin
on the opaque sidecar host. The wrapper exposes accessible loading/degraded/
error recovery and reload/fullscreen controls. Maverick shell navigation
accepts bounded scalar `od_project_id`/`od_run_id` values. Project deep links
bootstrap the real OpenDesign `/projects/<id>` route. Without a deep link, the
backend chooses the newest `createdAt`; with no projects the wrapper keeps
OpenDesign Home unmounted and shows only `Nuovo progetto`. Sidebar selections
and creation update shell-owned app params/history, so the sidebar and floating
Chat always share the same project context.

The shell theme is forwarded as a sanitized dark/light message. The patched
OpenDesign export maps its backgrounds, surfaces, borders, text, focus, dialog,
popover and scrollbar colors to Maverick tokens. The React patch uses a hosted
project view that never mounts `ProjectView`, `ChatPane`, resize/divider rails,
side-chat tabs, Home or the native workspace tabs. The file workspace remains
full width and the shell sidebar is the only project catalog. Its footer opens
the native `SettingsDialog` through a typed command, including in the empty
state. Every incoming shell/sidecar message requires both
the expected `event.origin` and `event.source`.

## Maverick Chat Integration

OpenDesign conversations appear as ordinary user-visible Maverick runtime
threads with `source_app_id: design-studio`. Chat adds an OpenDesign badge to
the sidebar row and active floating header, an OpenDesign filter, and delegates
submit/cancel/retry to Design Studio instead of bypassing the OpenDesign run
protocol with a direct runtime turn.

Design Studio stores only the durable correlation in
`maverick-runtime/conversation-bindings.json`: one OpenDesign project and
conversation resolve to one canonical Maverick runtime session/thread across
later turns and restarts. OpenDesign remains canonical for the conversation,
user/assistant messages, run records and result packages. Legacy correlations
are migrated by choosing the newest valid session for future turns without
rewriting or deleting historical runtime threads.

The composer exposes one generic source-app tools button. Only the actionable
Chat, Plan and Design modes are listed; informational capabilities without an
end-to-end action are not advertised. Submit, cancel and retry still use the
source app owner and its persisted runtime-session binding.

## SDK Flow

Design Studio is a first-party source-available platform app under `apps/design-studio`, not a workspace-local SDK-generated app. It still follows the same contract validation and hosted lifecycle expectations:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
npm test --if-present --prefix apps/design-studio
maverick app design-studio frontend build --json
maverick app design-studio cli list --json
maverick app design-studio mcp list --json
```

The app is installed into workspaces through the generic built-in app source registration and workspace binding flow. It must not be registered through app-specific bootstrap shortcuts.

## Contract Notes

The contract declares frontend, backend, CLI, MCP, lifecycle hooks, a bundled skill, referenceable `design_project` entities, standard view-state actions, Storage dependencies, and one app-owned HTTP sidecar.

Because Design Studio can create runtime sessions, it also implements the
trusted platform `runtime.cleanup_sessions` hook declared by
`permissions.runtime.cleanup_sessions`. Full runtime cleanup removes only the
matching app-owned OpenDesign correlation records and conversation bindings;
ordinary user backend calls cannot invoke that destructive hook.

The sidecar is sandbox-compatible because its mandatory generic
`process_policy` starts it under bubblewrap with an allowlisted environment,
read-only app bundle, writable validated app data root, isolated network
namespace, empty outbound list, resource/request limits, and an authenticated
Unix relay. Its loopback listener exists only inside that namespace; core never
publishes or falls back to a host TCP port. `HOME`, provider/runtime secrets,
cookies, Storage, operator paths, and other workspaces are absent. The generated
technical token uses the generic `${service.token}` substitution and is not the
relay capability.

OpenDesign verifies the complete materialized closure before every process
start. A cold launch after a core or sidecar restart can therefore take longer
than a warm relaunch even though the control record and bundle are healthy.
The sidecar health declaration gives `/api/ready` up to 120 seconds; failed
readiness still terminates the complete process group and returns a fail-closed
`sidecar_origin_unavailable` response. Browser-session idle expiry does not
replay an old ticket: the wrapper requests a fresh launch while reusing the
healthy process when it is still live.

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
SDK capability for the minimum project catalog, project file upload/read-back,
and batch archive routes needed by that surface, with a 30-second TTL, request
budget, explicit request/response limits, and no streaming. Reference access
remains GET-only. `core.app_sdk.app_sidecar` calls the core-owned Unix broker; Design
Studio never learns the OpenDesign port, `OD_API_TOKEN`, relay capability, or
database path. The capability is bound to workspace, local app, service,
surface, actor, and invocation and is revoked when the entrypoint finishes.
Reference calls use their own GET-only policy and cannot inherit MCP mutation
authority. Broker failure has no loopback or filesystem fallback.

An explicit OpenDesign project id is resolved through this SDK path by the
backend (and therefore the mounted frontend), CLI `get_project`, MCP
`design_studio_get_project`, and the standard Design Studio reference
resolve/summarize tools. CLI `create_project` and MCP
`design_studio_create_project` also create canonical OpenDesign projects.
Legacy `design_*` ids never become output identities; no OpenDesign data is
read directly from `app.sqlite` or duplicated in adapter state.

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
- `GET/POST /api/runs`, run status, SSE events, cancel, and result-package
  routes through the generic Maverick runtime stream

For run creation, Design Studio first validates the real project and
conversation through its short-lived `app_sidecar` capability. It then reserves
an app-owned OpenDesign run correlation and asks core for a source-app-stamped
runtime session, a durable stream, and a one-shot capability to the active
project directory. Existing conversation bindings supply the same
`runtime_session_id` for subsequent turns. Only correlation metadata is stored
under the active data generation in `maverick-runtime/correlations.json` and
`maverick-runtime/conversation-bindings.json`; terminal callback event IDs
are persisted there before acknowledgement so at-least-once callback replays
return without another OpenDesign request or state mutation. Prompts, provider
payloads, tokens, and host paths are excluded. Core owns provider selection, budgets,
interrupt, recovery, and normalized events. Design Studio alone owns the
OpenDesign SSE schema and writes terminal result packages for success, failure,
timeout, and cancellation.

Cancellation intent is persisted before core receives the interrupt request.
Terminal projection is monotonic: a later callback cannot replace an already
terminal run, and a failure delivered after a recorded cancel request is exposed
as `canceled` rather than regressing the OpenDesign run to `failed`. This rule is
applied identically to the direct runtime hook and the translated SSE stream.

The contract declares `permissions.providers.model_proxy: true` with `credential_source: core-vault` and `deliver_secrets_to_app: false`. It does not declare app-scoped provider secret reads. Provider keys stay in Maverick/Vault-owned flows, are not delivered to the browser, Design Studio backend, or OpenDesign sidecar, and are not written into `OD_MEDIA_CONFIG_DIR`. Provider errors are returned in OpenDesign's provider-model response shape (`ok`, `kind`, `latencyMs`, `status`, `detail`) so the bundled UI can handle unavailable provider state without learning raw credentials.

## Verification

Useful checks:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
python3 -m unittest apps/design-studio/tests/test_opendesign_adapter.py
python3 -m unittest tests/unit/apps/test_runtime_requests.py
python3 -m unittest apps.design-studio.tests.test_runtime_bridge
python3 -m unittest apps/design-studio/tests/test_opendesign_oci_import.py
python3 -m unittest apps/design-studio/tests/test_opendesign_materialization.py
python3 -m unittest apps/design-studio/tests/test_opendesign_migration.py
python3 apps/design-studio/service/sync_route_policy.py
python3 apps/design-studio/service/smoke_opendesign_runtime.py
python3 apps/design-studio/service/smoke_opendesign_migration.py
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
maverick app design-studio frontend build --json
maverick app design-studio mcp list --json
maverick app design-studio cli list --json
```

The app-owned `dev apply` command requires exactly one isolated changeset:
explicit repository-relative `changed_files`, or immutable `base_sha` plus the
current `head_sha`. It snapshots and propagates that set to every changed-suite
gate, then materializes a committed checkout with only those declared path
bytes overlaid. Builds and tests run from that checkout, so unrelated
shared-worktree changes cannot enter the run. Signed immutable runtime/web
registries are linked by digest, while installed Node dependencies are copied
into the isolated checkout before execution. It emits
bounded JSON containing actions, durations, digests, cache state, readiness,
and rollback. Frontend, backend, overlay, runtime, hosting, docs, and
release-only changes select only their owned gates; documentation does not
trigger OCI, backend is not run twice, and `changed_suite` is not unconditional.
Changes to `patches/series.json` are compared semantically with the frozen base:
`web-build` and `web-react` entry updates remain web-only, while `runtime` or
unknown series changes select the OCI pipeline.

`dev benchmark` performs the automatic real React-patch-to-live proof. It
changes patch bytes in an isolated copy, forces new source/build and overlay
digests without a source-cache hit, activates through readiness and the scoped
browser-remount event, restores the exact initial selection, and records phase
timings. The canonical ceiling is 180 seconds.

Production-path acceptance runs the official materialized OCI daemon, the
real Maverick ASGI host and sidecar broker, the real Storage app, and headless
Chromium against two temporary workspaces. The only provider substitute is an
external statically compiled process that implements the Codex app-server
protocol; it crosses the normal sandbox/process boundary and writes the test
artifact into the granted project root. It is not an in-process runtime mock.

```bash
npm run test:e2e:quick --prefix apps/design-studio
npm run test:e2e:affected --prefix apps/design-studio
npm run test:e2e:release --prefix apps/design-studio -- \
  --evidence-output /owned/evidence/opendesign-ui-release.json
npm run test:e2e:migration --prefix apps/design-studio \
  > /owned/evidence/opendesign-migration.json
python3 apps/design-studio/service/aggregate_opendesign_release_evidence.py \
  --ui /owned/evidence/opendesign-ui-release.json \
  --migration /owned/evidence/opendesign-migration.json \
  --benchmark /owned/evidence/opendesign-change-to-live.json \
  --output /owned/evidence/opendesign-release.json
python3 -m unittest apps.design-studio.tests.test_production_acceptance
```

For a deployed installation, run the separate hosted-origin smoke from the
repository host. It uses an existing active operator session without logging
its value, keeps Chromium TLS verification enabled, and verifies the isolated
HTTPS iframe, secure bootstrap cookie, reload, persisted-project lookup, and
deep link. Supplying `--storage-input-path` additionally creates a temporary
OpenDesign project, exercises Storage import, a real runtime run and SSE,
result packaging, Storage export/read-back, and deletes only that temporary
project.

```bash
npm run test:e2e:hosted --prefix apps/design-studio -- \
  --platform-origin https://maverick.example \
  --auth-sessions-file data/control-plane/json/identity/auth_sessions.json \
  --project-id <canonical-opendesign-project-id> \
  --storage-input-path storage/generated/design-studio/hosted-acceptance-input.md \
  --evidence-output apps/design-studio/service/opendesign_hosted_acceptance_0_16_1.json
```

The optional evidence file contains only public origins and bounded acceptance
booleans. It never records the selected platform session, bootstrap cookie,
browser headers, prompts, provider payloads, or environment values.

`npm run test:e2e` aliases the complete release profile. The quick profile
covers changed UI behavior, and affected composes integration
coverage from the diff. The final browser release profile covers thirteen UI
scenarios: login/open with the
fixed Maverick sidebar, project creation and navigation through that sidebar,
absence of the native home project strip and Chat pane, Storage import, runtime
start, incremental SSE, generated-file preview, idempotent cancel, Storage
export and manifest read-back, core/sidecar restart with explicit `/api/ready`
checks, deep link, workspace A/B isolation, exact route denial, browser
credential non-disclosure. Real-daemon migration/rollback on marked fixture
copies is a separate gate, not repeated inside UI cases. The final aggregator
requires the exact unique set of thirteen canonical UI ids, explicit restart
and workspace-isolation scenarios, every source/forward preservation proof, and
the independent rollback result. Before emitting `passed`, it verifies the
selected signed overlay and matches its upstream commit, lockfile digest,
runtime compatibility, and both web patch digests to the current bundle,
supply-chain inventory, and `patches/series.json`. The schema-3
`service/opendesign_release_acceptance_0_16_1.json` remains redaction-safe
historical evidence but predates this series binding; a new real release run
must replace it with schema 4 before it is current release evidence. Each UI
scenario carries the full app/runtime correlation join, while the separate
rollback scenario carries only bounded migration proof.
The 24 global criteria and stable evidence references are tracked in
`service/opendesign_production_acceptance_0_16_1.json`.

Current intentional omissions:

- generated OpenDesign assets and dependency closures stay out of source control
- immutable runtime and web registries stay ignored; only canonical digest contracts and redaction-safe release evidence are committed
- real workspace migration remains unauthorized; migration tests operate only on marked fixtures and controlled copies
- the source-build baseline remains a separate fallback certification; the primary OCI artifact is pinned and its real acceptance evidence is committed
- provider proxying is limited to OpenDesign model discovery through Maverick's active workspace provider; generation/chat provider routes remain unavailable in sandbox mode
- full-access terminal, Local CLI, and host-folder import are not part of the sandbox MVP
