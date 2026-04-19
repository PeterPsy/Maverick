# Maverick v3 App Port Plan Template

Use this structure for every v2-to-v3 app plan.

## 1. Architecture Alignment

- v3 docs read:
- relevant core modules inspected:
- target app role in v3:
- app-store vs workspace-local decision:
- core must stay app-agnostic because:

## 2. V2 App Inventory

- source path:
- manifests/contracts:
- frontend:
- backend:
- MCP:
- CLI:
- skills:
- lifecycle hooks:
- storage/data:
- secrets/env:
- tests:
- external dependencies:
- hardcoded paths/services:

## 3. Target V3 Contract

- app id:
- version:
- distribution mode:
- source access:
- declared surfaces:
- frontend mount:
- backend entrypoint:
- MCP/CLI entrypoints:
- skill assets:
- storage roots:
- data schema version:
- lifecycle hooks:
- health contract:
- export/import/migration:
- rollback semantics:

## 4. File-By-File Port Map

| v2 path | v3 target | category | action | reason |
| --- | --- | --- | --- | --- |

## 5. Core Gaps

| gap | why app needs it | generic core owner | docs/tasklist update | blocking? |
| --- | --- | --- | --- | --- |

Only include gaps that are generic core capabilities. Do not use this section for app-specific behavior.

## 6. Implementation Phases

1. documentation and tasklist update
2. contract and app skeleton
3. tests for stable contracts and app mounting
4. frontend/backend/MCP/CLI/skills implementation
5. build artifacts, if required by distribution mode
6. deployment and smoke verification
7. cleanup review
8. commit and push

## 7. Verification

- contract parser:
- app build:
- app tests:
- core tests:
- MCP/CLI smoke:
- live route smoke:
- legacy path scan:
- generated artifact check:

## 8. Open Questions

List only decisions that block safe implementation.
