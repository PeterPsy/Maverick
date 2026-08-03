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
allowlist. WP5 replaces source-tree measurements with the staged runtime
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
