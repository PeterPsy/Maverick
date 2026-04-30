# Runtime and providers

## Runtime model

- The core owns runtime sessions, turns, events, process state, and lifecycle.
- A provider adapter owns backend-specific protocol details.
- The runtime session id and provider thread id are intentionally different.
- App UIs may create runtime sessions through generic core surfaces.

## Codex adapter expectations

```text
runtime/sessions/<runtime_session_id>/
  events.json
  turns.json
  processes.json
  state.json
  bin/
```

## Invariants

- Provider homes are session-local.
- Child sessions inherit workspace scope unless a trusted control-plane action changes it.
- Runtime skills come from workspace-owned Skills app data, not user-global skill directories.


## Runtime versus provider

| Concept | Owner | Purpose |
| --- | --- | --- |
| Runtime session | Maverick core | Workspace-scoped lifecycle container |
| Runtime turn | Maverick core | One submitted unit of work |
| Provider thread | Provider adapter | Backend-specific conversation state |
| Runtime event | Maverick core | Observable execution timeline |

## Skill materialization

Runtime skills are workspace-owned records managed by the Skills app. Provider adapters may materialize them into a session home, but app source `skills/` directories are templates, not direct runtime inputs.
