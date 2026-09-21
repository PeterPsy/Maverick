# GitHub Actions

Workspace-local Maverick utility for dispatching and inspecting GitHub Actions
workflows through a GitHub App installation.

The app reads these Core Secrets logical names:

- `github-app-id`
- `github-installation-id`
- `github-app-private-key`

Authenticated workspace administrators can invoke the same redacted operations
through the mounted backend. Core still injects Vault grants per request; the
backend never returns credential material.

Default target:

- repository: `giuntiocram/maverick-glasses-ios`
- branch: `maverick-integration`
- workflow: `ios-install-device.yml`

## Validate

```bash
maverick core cli run core.app-sdk.validate --app-id github-actions --json
```

## Workspace-Local Install

```bash
maverick core cli run core.app-sdk.register-local --app-id github-actions --workspace default --json
maverick core cli run core.app-sdk.install-local --app-id github-actions --workspace default --json
```

## Use

```bash
maverick app github-actions cli run github-actions --json --arguments-json '{"action":"dispatch_and_wait","timeout_seconds":900}'
```
