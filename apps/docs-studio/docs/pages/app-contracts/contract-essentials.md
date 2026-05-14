# Contract essentials

## Required identity

```json
{
  "app_id": "docs-studio",
  "contract_version": "1.0",
  "name": "Docs Studio",
  "version": "0.1.0",
  "distribution": {
    "mode": "workspace_local",
    "source_access": "editable"
  },
  "presentation": {
    "frontend_role": "workspace"
  }
}
```

## Contract rule

The contract is not documentation-only metadata. If it declares a surface, that surface must exist and be discoverable.

## Completeness baseline

- `README.md` describes purpose, surfaces, storage, and validation.
- Contract smoke tests parse the app contract.
- Declared skills match real `skills/<skill_id>/SKILL.md` templates.
- Intentional omissions are documented.


## Contract completeness

A valid contract is necessary, but not sufficient. A real app should also have working entrypoints, truthful README documentation, smoke tests, and lifecycle behavior that matches what it declares.

## Declared means implemented

If the contract declares `mcp_tools`, discovery must list those tools. If it declares `reference_entities`, the app should expose manifest, search, resolve, and summarize behavior. If it declares frontend rebuild, the build must work.
