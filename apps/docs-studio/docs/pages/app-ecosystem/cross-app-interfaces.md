# Cross-app interfaces

Cross-app work should happen through declared interfaces, not direct file or database access.

## Interface patterns

| Need | Interface |
| --- | --- |
| Link to a record | reference entity |
| Render a structured payload | widget |
| Run a command | scoped CLI |
| Use a structured tool | scoped MCP |
| Coordinate multi-step work | runtime agent orchestration |
| Receive app changes | app data events |

## Contract-first thinking

Future cross-app consumers should declare what interface type they require, not which private file they expect. The core can then resolve installed and enabled providers for that interface in the active workspace.

## Anti-pattern

```text
apps/chat imports ../../checklist/frontend/widget.tsx
```

That couples host and widget owner at build time. The Maverick model uses registry-driven iframe widgets instead.
