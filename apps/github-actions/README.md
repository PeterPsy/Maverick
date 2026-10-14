# GitHub Actions

Installation-level Maverick utility for dispatching and inspecting GitHub Actions
workflows through a GitHub App installation.

The source lives in `apps/github-actions/` on the Maverick `design` branch.
Workspace installation binds to this shared source; credentials and app data
remain scoped to each workspace.

The app reads these Core Secrets logical names:

- `github-app-id`
- `github-installation-id`
- `github-app-private-key`

Authenticated workspace administrators can invoke the same redacted operations
through the mounted backend. Core still injects Vault grants per request; the
backend never returns credential material.

The `run_jobs` action returns only redacted job assignment metadata, including
required labels and the assigned runner name when GitHub has selected one. It
is intended for diagnosing queued physical-device jobs without requiring extra
repository-administration permission.

Default target:

- repository: `giuntiocram/maverick-glasses-ios`
- branch: `maverick-integration`
- workflow: `ios-install-device.yml`

## Validate

```bash
maverick core cli run core.app-sdk.validate --app-root apps/github-actions --json
```

## Install

```bash
maverick core cli run app.github-actions.install --json
```

## Use

```bash
maverick app github-actions cli run github-actions --json --arguments-json '{"action":"dispatch_and_wait","timeout_seconds":900}'
```
