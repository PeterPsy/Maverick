# Generated Artifact Policy

Maverick currently commits selected generated frontend artifacts under `apps/*/frontend/dist/`.

This is intentional for built-in apps that must mount in a fresh checkout before a frontend rebuild step is available.

## Rules

- Edit source files when source exists.
- Rebuild the app after changing source.
- Commit generated `frontend/dist/` only for built-in apps whose contract serves that directory.
- Do not commit local runtime output, logs, caches, workspace data, screenshots, or temporary exports.
- Do not commit source maps that expose local paths unless explicitly reviewed.
- CI should verify that source-built apps can rebuild successfully.

## Rationale

Maverick's app contract serves declared static frontend output. During the pre-release period, committed dist assets keep app mounting deterministic while the app packaging and release pipeline matures.

This policy should be revisited before the first stable release.
