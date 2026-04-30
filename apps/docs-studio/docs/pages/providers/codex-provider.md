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

## Sandbox hardening

- Drop inherited MCP/app/plugin configuration from operator Codex homes.
- Remove provider-generated `.system` skills from runtime homes.
- Bind only required helper binaries such as `codex` and `rg`.
- Keep readable and writable roots constrained to the workspace.
- Fail closed if the host cannot create the required sandbox.
