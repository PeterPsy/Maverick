# Core Gap Rules

Use this reference when an app appears to need changes in Maverick v3 core.

Allowed core changes:

- generic app mounting capability
- generic frontend/backend/MCP/CLI/skills discovery
- generic policy enforcement
- generic secret binding and delivery
- generic observability events
- generic lifecycle hook execution
- generic export/import/migration plumbing
- generic recovery and health surfaces

Disallowed core changes:

- app-specific routes in core
- app-specific business logic
- app-specific UI behavior
- v2 compatibility endpoints
- special cases for a named app
- storage or path rules that only make sense for one app

Decision rule:

If another unrelated app could use the same capability without knowing the original app, it may belong in core. Otherwise, it belongs in the app.
