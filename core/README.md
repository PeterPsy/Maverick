# Maverick Core

This tree is the package root of the Maverick core.

The target architecture is defined in:

- `docs/architecture/core_architecture.md`

The core is organized by domain, not by legacy buckets.

Repository rules for this tree:

- core code lives directly under `core/`
- do not add wrapper folders such as `backend/`, `runtime_backend/`, or `app/`
- do not add an ambiguous `core/core/` subtree
- if shared internal helpers are needed, use a clearer package name such as `shared/`

Each domain should prefer small files with explicit names.
