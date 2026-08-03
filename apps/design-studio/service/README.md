# Design Studio OpenDesign Sidecar

Design Studio starts `opendesign_launcher.py` as the declared Maverick sidecar.
The launcher requires a curated OpenDesign bundle at:

```text
service/vendor/open-design/
```

The bundle must come from upstream `nexu-io/open-design` tag
`open-design-v0.10.1`, commit
`eb245799adf07e7727ad5f970485d809bad5780e`.

To materialize it from a verified checkout:

```bash
python3 apps/design-studio/service/package_opendesign.py \
  --source /path/to/open-design \
  --force
```

The packaging manifest is `opendesign_bundle.json`. It copies only the daemon,
web static app source, required workspace packages, and bundled design assets,
then narrows the generated pnpm workspace and runs install/build so the daemon
and its workspace package dependencies have runtime `dist/` outputs. Runtime
sidecar startup does not build OpenDesign on demand. Desktop, packaged Electron,
deploy, e2e, broad plugin marketplace, and tool trees are excluded from the
Maverick sandbox bundle.

The bundle is a generated artifact. Keep `service/vendor/open-design/` out of
source control, including `node_modules`; commit only the manifest, packager,
docs, and smoke script. A Phase 3 verification must run:

```bash
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
```

That smoke fails when the bundle is absent, when required build outputs are
missing, when host-only OpenDesign trees were included, or when the Maverick
proxy cannot reach the real sidecar. If the bundle is absent or not
installed/built, the declared Maverick runtime fails closed. There is no runtime
compatibility fallback.

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
safe static trees plus Maverick Storage import/export handlers. The artifact
manifest no longer duplicates this route catalog. WP5 replaces source-tree measurements with the staged runtime
closure, SBOM, NOTICE, license inventory, native load proof, and artifact
provenance.

## Versioned data generations

`opendesign_generation_control.py` defines the strict app-owned `control.json`
used for coordinated bundle and data activation. It validates verified artifact
digests and real `instances/<generation>/data/` directories, rejects unknown
fields and symlinks, and writes with same-directory temp, file `fsync`, atomic
replace, and directory `fsync`. The same module strictly validates and writes
migration journals and reconciles them against the active triple. Migration and
rollback orchestration are added in WP6; the current launcher must not select
this control file early.

Run the G4 filesystem and crash proof with:

```bash
.venv/bin/python -W error::ResourceWarning -m unittest \
  tests.architecture.test_design_studio_data_generation_proof -v
```
