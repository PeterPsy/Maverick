# Design Studio OpenDesign Sidecar

Design Studio starts `opendesign_launcher.py` as the declared Maverick sidecar.
The launcher prefers a curated OpenDesign bundle at:

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
then runs the recursive pnpm build so the daemon and its workspace package
dependencies have runtime `dist/` outputs. Runtime sidecar startup does not
build OpenDesign on demand. Desktop, packaged Electron, deploy, e2e, broad
plugin marketplace, and tool trees are excluded from the Maverick sandbox
bundle.

If the bundle is absent or not installed/built, the declared Maverick runtime
fails closed. The launcher runs `opendesign_compat.py` only when
`MAVERICK_OPENDESIGN_ALLOW_FALLBACK=1` is set manually for diagnostics or
focused tests; it is not the production OpenDesign daemon.
