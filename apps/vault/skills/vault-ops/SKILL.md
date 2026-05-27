---
name: vault-ops
description: "Use Vault safely for Active Credentials, Connection Issues, Advanced details, and redaction-safe Core Secrets operations."
---

# Vault Operations

Vault is the Active Credentials, Connection Issues, and Advanced details surface over `core.secrets`. It is not the owner of secret values.

Use Vault's app-owned CLI or MCP surface first to confirm the redaction-safe operating model:

```bash
maverick app vault cli run vault --json
maverick app vault mcp call maverick_vault
```

For actual secret metadata and mutations, use the core-owned secret surfaces exposed by that manifest. Never ask Vault, app data files, workspace files, chat transcripts, generated artifacts, or browser bundles for raw secret values.

Authority rules:

- Treat `core_surfaces.read_only` as redaction-safe admin review surfaces.
- Treat `core_surfaces.mutative_full_access` as privileged operations that require an explicit full-access operator/admin context.
- Treat `core_surfaces.admin_http` as platform-admin HTTP surfaces; raw values may be accepted on create/rotate requests but must never be reported back.

Grant review rules:

- `app.backend` grants must target logical names declared by the app contract under `permissions.secrets.read`.
- `app.backend` delivery targets use `maverick://app.backend/*` or a narrower `maverick://app.backend/<surface>` target.
- Expired, disabled, revoked, missing, or non-deliverable grants should be treated as configuration findings, not as usable secret access.
- Browser or user-directed actions are not a Vault UI workflow unless a controlled consumer is implemented and documented.

When reporting findings, include only secret ids, aliases, labels, statuses, app ids, logical names, grant ids, target patterns, expiry, and audit metadata. Do not include or infer raw values.
