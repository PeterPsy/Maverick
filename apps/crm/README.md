# CRM

Forkable workspace CRM for accounts, contacts, deals, activities, and business relationships.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `crm-ops` skill, persisted CRM view-state actions, and reference entities for all primary record types.
- App-owned storage is SQLite under `data/crm/crm.sqlite`.
- CRM is one of the repository reference apps for complete record-centric contract coverage.

## SDK Flow

```bash
./scripts/maverick app validate crm --workspace default
./scripts/maverick app register-local crm --workspace default
./scripts/maverick app install-local crm --workspace default
./scripts/maverick app status crm --workspace default
./scripts/maverick app package crm --workspace default
```
