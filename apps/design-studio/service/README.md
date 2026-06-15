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
