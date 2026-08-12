# Codex provider

Codex is the first concrete runtime backend, not the architectural definition of Maverick runtime.

## Runtime flow

```text
runtime session -> Codex app-server -> provider thread -> runtime events
```

The adapter should:

- prepare a runtime-scoped `CODEX_HOME`
- launch `codex app-server --listen stdio://`
- create or resume one provider thread per runtime session
- submit turns with `turn/start`
- normalize provider events into Maverick runtime events

## Subscription usage

Codex declares `supports_subscription_usage` and implements the optional provider usage adapter. Maverick Core reads the operator Codex login server-side, fetches account and model-specific subscription windows, and emits only the redaction-safe provider usage contract. The Settings app reads that contract through the admin-only `GET /api/providers/usage` endpoint; access tokens, refresh tokens, account ids, email addresses, and raw upstream errors never enter the browser payload.

Usage reads are independent from provider selection and platform-settings loading. Authentication or upstream failures therefore render an unavailable state without blocking model configuration or runtime administration.

## Sandbox hardening

- Drop inherited MCP/app/plugin configuration from operator Codex homes.
- Remove provider-generated `.system` skills from runtime homes.
- Bind only required helper binaries such as `codex` and `rg`.
- Keep readable and writable roots constrained to the workspace.
- Fail closed if the host cannot create the required sandbox.
