# Design Studio OpenDesign Sidecar

Design Studio starts `opendesign_launcher.py` as the declared Maverick sidecar.
The launcher requires an immutable curated OpenDesign bundle below the verified
registry:

```text
service/vendor/open-design/<artifact-sha256>/
```

The primary distribution is the upstream image
`ghcr.io/nexu-io/od:0.16.1`, pinned to OCI index
`sha256:eb1c9d55532ffd2088a4a71951cffd273dff65e96e077bcef8c8bac3a6e1f1a1`
and linux/amd64 manifest
`sha256:170f56cdeb3a213423af150d4095b7729814eaf0ad26a99be7fab2344f0f5cd1`.
The image labels and SLSA attestation bind it to upstream commit
`276b4d8e970bc143d7ad060181a89a834e3d9caf` and release `0.16.1`.

Import the immutable release without Docker or a local Next build, then
materialize it:

```bash
python3 apps/design-studio/service/import_opendesign_oci.py \
  --signing-key /secure/path/opendesign-provenance-key.pem
python3 apps/design-studio/service/materialize_opendesign.py
```

Import is fail-closed for agent runs. It requires a live
`MAVERICK_RUNTIME_SESSION_ID` in its process ancestry. Each command runs in a
new process group; loss of the runtime attachment or termination stops the whole
group. It also refuses to begin below 3 GiB available memory. The registry
client accepts only the two pinned HTTPS hosts, validates every descriptor,
layer size and digest, requires the exact OCI config labels and SLSA subject,
and streams layers through owned temporary files. Layer extraction rejects path
escape, unsafe links and special files and implements OCI whiteouts without
following filesystem links.

`opendesign_bundle.json` is the single distribution contract. Two independent
pulls reconstruct and inventory the root filesystem, apply the one exact
preimage-bound compiled boundary patch, stage the image's own musl loader, Node
runtime, daemon, static web and native dependency closure, and generate the
archive, file manifest, SBOM, licenses, NOTICE and signed provenance. Every
output must match byte-for-byte before publication. The launcher invokes only
that imported loader and Node binary; the app contract deliberately declares no
package manager and core therefore does not mount a host Node runtime.

The launcher revalidates the materialized files on every new process. This is
part of the artifact trust boundary and can dominate a cold start when the OS
page cache is cold. Design Studio therefore declares a 120-second startup
health budget for `/api/ready`. Core keeps serving its own `/health` endpoint
during that wait, retries the authenticated Unix-relay probe, and tears down the
whole confined process group if readiness still fails. A later browser launch
must start a new process cleanly; no half-started relay or browser session is
reused.

The source-build recipe remains under `fallback_build` only as a separately
reviewed fallback. It is not part of the primary import or runtime path and must
not be used to replace a failed OCI verification.

The complete source-suite baseline is not part of OCI import and does not gate
the pinned image verification. It remains a separate fallback-build acceptance
on adequate capacity:

```bash
python3 apps/design-studio/service/certify_opendesign_upstream.py \
  --source /path/to/exact-unpatched-open-design-v0.16.1 \
  --output-dir /owned/output/opendesign-upstream-acceptance
```

That command performs one frozen install and exactly two complete suite
processes—web, then daemon—with one worker, no shard, exclusion, or retry. Its
record is `opendesign_upstream_baseline_0_16_1.json`. A capacity stop is an
infrastructure blocker to move to a suitable builder, not a reason to resume a
per-file prefix or construct a retry framework.

The generated artifact and its external file manifest, CycloneDX SBOM, license
inventory, NOTICE, signed provenance, signature, and public key stay under
ignored `service/artifacts/`. The committed manifest pins every digest and the
artifact size. `materialize_opendesign.py` verifies the complete signed set and
atomically installs it into its digest-named directory below ignored
`service/vendor/open-design/`. An existing digest directory is immutable: it is
accepted only when every file still verifies and is never overwritten after a
mismatch. The launcher verifies the registry, the current manifest pin, and the
active bundle/data triple before start.

Repository-wide Python bytecode checks must exclude `service/vendor/**`. Running
`compileall` across the imported closure creates `__pycache__` files inside the
otherwise immutable digest directory, which correctly makes subsequent launcher
verification fail closed. Compile only repository-owned Python sources, for
example with `rg --files ... -g '!apps/design-studio/service/vendor/**'` piped to
`python3 -m py_compile`.

A release verification must run:

```bash
python3 apps/design-studio/service/smoke_opendesign_runtime.py
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
```

The committed `opendesign_oci_acceptance_0_16_1.json` records the real double
import, rootfs inventory, materialization, native loads, bearer boundary,
SQLite integrity and daemon/static smoke. Upstream's root package still reports
`0.15.1`; release identity is therefore taken from the pinned image labels,
attestation and `apps/packaged/package.json` version `0.16.1`. The official
image contains `node-pty` without a loadable linux binary. Terminal and PTY
routes remain denied, while required `better-sqlite3` and `blake3-wasm` load
from the imported closure.

That smoke fails when the bundle is absent, its digest/file manifest differs,
required outputs are missing, host-only OpenDesign trees are present, or the
Maverick proxy cannot reach the real sidecar. The declared runtime always fails
closed; there is no source-tree, build-on-startup, or loopback compatibility
fallback.

## Confined process boundary

The app contract opts into the mandatory generic sidecar `process_policy`.
Core starts the launcher under bubblewrap with a fixed allowlisted environment,
the app source mounted read-only at `/app`, the resolved Design Studio data root
at `/data`, a read-only minimal runtime closure, an isolated network namespace,
and no outbound targets. `HOME`, operator/provider runtime homes, provider keys,
Maverick runtime tokens, bootstrap secrets, cookies, Storage, and other
workspaces are not mounted or inherited.

OpenDesign's TCP listener is internal to that network namespace. Core health and
proxy traffic use an authenticated mode-`0600` Unix relay; there is no host TCP
listener or loopback fallback. The contract bounds address space, open files,
and concurrent proxy requests. Shutdown and failed startup terminate the whole
bubblewrap process group, including descendants, and remove the relay directory.
`OD_API_TOKEN` is generated as `${service.token}` and remains distinct from the
relay capability; neither value is returned to the browser.

The declared generic `browser_origin` profile gives the web app its own opaque
host and a Maverick-brokered, host-only session. Bootstrap is a one-shot form
POST; the ticket is absent from URLs, redirects, cookies, audit payloads, and
sidecar requests. Core strips platform cookies, sidecar cookies, unsafe
redirects, and technical authorization headers, applies no-store/no-referrer
headers plus the contract CSP, and refuses to fall through to platform routes.

`frontend/src/App.tsx` consumes that production browser-origin contract as a
minimal full-bleed host. It uses a transient form POST to the exact bootstrap
URL returned by core, then clears the ticket input. It never uses the legacy
path-mounted `proxy_url`, constructs an OpenDesign API URL, stores a token, or
renders a second project list. A scalar `od_project_id` selects the real
`/projects/<id>` router path at bootstrap; `od_run_id` is forwarded only in the
versioned, origin/source-bound navigation message. Reload obtains a new
one-shot ticket instead of replaying an old session bootstrap.

The OpenDesign contract uses a 16 GiB virtual-address ceiling. This is a bound
on address space, not a claim of physical allocation: Node/V8 and WebAssembly
reserve multi-gigabyte virtual regions at startup, and the real curated daemon
smoke proves that a smaller 4 GiB ceiling fails closed before readiness.

Production-boundary proof:

```bash
python3 -W error::ResourceWarning -m unittest \
  tests.integration.app_hosting.test_sidecar_execution \
  tests.integration.app_hosting.test_sidecar_browser_origin
```

## Pinned 0.16.1 inventories

`inventory_opendesign.py` reads a clean checkout of the exact
`open-design-v0.16.1` tag at commit
`276b4d8e970bc143d7ad060181a89a834e3d9caf`. It resolves Express route
registrations into `opendesign_routes_0_16_1.json` and records the tracked
source tree, package manifests, declared licenses, lockfile digest, and native
dependencies in `opendesign_supply_chain_0_16_1.json`.

Regenerate both files from an exact checkout:

```bash
python3 apps/design-studio/service/inventory_opendesign.py \
  --source /path/to/open-design-v0.16.1 \
  --routes-output apps/design-studio/service/opendesign_routes_0_16_1.json \
  --supply-chain-output apps/design-studio/service/opendesign_supply_chain_0_16_1.json
```

The command fails for a dirty checkout, a wrong commit/tag, or an unresolved
route registration. The route classification is deny-by-default and scoped to
the browser sidecar origin; app-entrypoint capabilities use a separate
allowlist. Multi-segment upstream splats are classified blocked because the
generic policy limits dynamic parameters to one segment. Provider model
discovery is handled by Maverick rather than forwarded.

After regenerating the inventory, synchronize or verify the reviewed exact
contract policy with:

```bash
python3 apps/design-studio/service/sync_route_policy.py --write
python3 apps/design-studio/service/sync_route_policy.py
```

The check accounts for every inventoried method/template, omits `USE /api` and
multi-segment splats so deny-by-default applies, and adds only the approved
safe static trees, the exact one-segment raw read used for Storage import
verification, plus Maverick Storage import/export handlers. Nested raw reads
remain denied; project export uses OpenDesign's exact batch archive route. The artifact
manifest does not duplicate this route catalog. The staged runtime closure is
instead bound to its file manifest, SBOM, NOTICE, license inventory, native
load proof, deterministic build metadata, and signed provenance.

## Versioned data generations

`opendesign_generation_model.py` owns the strict value objects, while
`opendesign_generation_control.py` owns atomic `control.json` and journal I/O.
Together they validate verified artifact digests and real
`instances/<generation>/data/` directories, reject unknown fields and symlinks,
and write with same-directory temp, file `fsync`, atomic replace, and directory
`fsync`. The launcher uses only the exact active triple: its digest selects one
verified immutable bundle directory and its generation selects the only
directory exported as `OD_DATA_DIR`. It never selects a bundle or data directory
by name, timestamp, symlink, or fallback.

Controlled migration is split by responsibility: `opendesign_migration.py`
coordinates freeze, drain, staging, cutover, rollback and recovery;
`opendesign_migration_files.py` owns bounded copies, locks and cleanup;
`opendesign_migration_legacy.py` moves legacy projects and imports only through
the governed runtime API. It refuses any root without the explicit
fixture/controlled-copy marker and does not authorize real workspace migration.

Run the G4 filesystem and crash proof with:

```bash
.venv/bin/python -W error::ResourceWarning -m unittest \
  apps/design-studio/tests/test_data_generation_proof.py \
  apps/design-studio/tests/test_opendesign_migration.py -v
```

WP6 also has a real-daemon proof:

```bash
python3 apps/design-studio/service/smoke_opendesign_migration.py
```

It creates only temporary, explicitly marked controlled copies. The first
scenario migrates a 0.10.1 fixture into a staging generation served by the
materialized 0.16.1 OCI daemon, creates the canonical project and file through
OpenDesign APIs, reads the uploaded bytes back, verifies both SQLite databases,
and proves the retained source tree is unchanged. A second scenario performs a
real daemon cutover and rollback, reactivates the previous generation, runs
health/database/project checks and proves the forward generation remains
untouched. Distinct 0.10.1/0.16.1 bundle+data atomicity and crash points remain
covered by the fixture injection suite. The redaction-safe result is pinned in
`opendesign_migration_acceptance_0_16_1.json`; no real workspace migration is
authorized.

## Maverick runtime bridge

The OpenDesign run collection, status, cancel, event stream, and result-package
routes are classified `handled_by_core`. The generic host invokes the Design
Studio backend; it never teaches core an OpenDesign route or event type. The
backend validates the OpenDesign project and conversation through the governed
entrypoint broker, persists only run-to-session correlation metadata in the
active generation, and returns a generic `runtime_session_request` with a
stable idempotency key.

Core creates the user-visible source-app session, resolves the active project
directory through a short one-shot app-data capability, and appends a durable,
provider-neutral stream. Its ASGI response applies backpressure by awaiting
each translated SSE event, sends keepalives while idle, and resumes from
`Last-Event-ID`. Cancel, cleanup, and stream reads fail closed unless workspace
and source-app ownership match. Backend restart closes an interrupted app turn
without creating an automatic duplicate; the same OpenDesign request remains
idempotent.

The bridge writes cancel intent before requesting the generic core interrupt.
Terminal callbacks and SSE translation share one monotonic projection: terminal
states do not regress, and a failure observed after cancel intent is recorded is
projected as `canceled`. This keeps the OpenDesign status, terminal SSE event,
and result package consistent when provider termination and callback delivery
race.

Run the WP7 proof with:

```bash
python3 -m unittest \
  tests.unit.runtime_streams.test_app_streams \
  tests.unit.api.test_app_runtime_cleanup_requests \
  tests.integration.app_hosting.test_sidecar_core_routes \
  tests.integration.recovery.test_backend_restart \
  apps.design-studio.tests.test_runtime_bridge -v
```

## Canonical project and Storage adapter

`adapter-state.json` stores only view state plus import/export lifecycle jobs.
The sealed pre-migration `state.json` is never created, migrated, or opened for
writing by the adapter. Canonical create/list/get operations use the governed
OpenDesign API. A `design_*` value is accepted only as an alias found in
`opendesign/legacy-project-map.json`; output identity remains
`od_project_id`.

Storage imports are read through the selected dependency, uploaded to the real
OpenDesign project, and verified by SHA-256 read-back. Terminal run exports use
the real OpenDesign batch archive and write a run-scoped package through
Storage. The official OCI smoke performs this flow in a temporary workspace:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  apps/design-studio/service/smoke_opendesign_sidecar.py
```

## Production-path acceptance

WP10 is exercised by `tests/opendesign_product.e2e.mjs`. It creates a new
temporary Maverick installation with two synthetic workspaces, boots the
materialized official `ghcr.io/nexu-io/od:0.16.1` closure through the declared
launcher, and drives the isolated UI with real Chromium. Core, the Unix sidecar
relay, Storage import/export, restart recovery, route policy, browser sessions,
and migration smoke all use their production code paths. A statically compiled
external Codex app-server protocol fixture supplies deterministic model output
without entering the OpenDesign or core process and without logging prompts.
The browser asserts the isolated `/api/ready` response before onboarding and
again after the core/sidecar restart, then verifies the persisted project.

Run and validate the committed redaction-safe records with:

```bash
npm run test:e2e --prefix apps/design-studio -- \
  --evidence-output apps/design-studio/service/opendesign_product_acceptance_0_16_1.json
python3 -m unittest apps.design-studio.tests.test_production_acceptance
```

`opendesign_product_acceptance_0_16_1.json` contains the fourteen browser
scenario results and nine-key correlation join. It contains no prompt, cookie,
bearer, provider payload, environment, host path, or secret value.
`opendesign_production_acceptance_0_16_1.json` maps every global acceptance
criterion to a stable test, proof, or canonical document. Neither record
authorizes migration of an existing workspace data root.
