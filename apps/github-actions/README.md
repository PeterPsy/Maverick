# GitHub Actions

Installation-level Loopino utility for dispatching and inspecting GitHub Actions
workflows through a GitHub App installation.

The source lives in `apps/github-actions/` on the installation's active source
branch at its deployed commit. Inspect and preserve that branch before work;
follow the root working agreement rather than checking out a historical branch.
The clean-install candidate is `loopino/phase1`; `design` is predecessor history.
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

Repository and dispatch ref are required inputs. No company repository,
branch or device ID is preconfigured. Use the coordinator-published repository
and exact reviewed commit SHA. The iOS install workflow defaults to
`build_only=true` and `launch_app=false`; device installation requires an explicit
workflow input change.

## Validate

```bash
loopino core cli run core.app-sdk.validate --app-root apps/github-actions --json
```

## Install

```bash
loopino core cli run app.github-actions.install --json
```

## Use

```bash
loopino app github-actions cli run github-actions --json --arguments-json '{"action":"dispatch_and_wait","repository":"OWNER/REPOSITORY","ref":"REVIEWED_COMMIT_SHA","timeout_seconds":900}'
```

## SDK Flow

Validate this shared app with `core.app-sdk.validate` before SDK packaging. It is
retained as source and excluded from the standard clean bootstrap/catalog
selection. The coordinator chooses the repository and reviewed source commit
for any dispatch; local development credentials are never copied into the app.

## Contract Notes

Backend, CLI and MCP use the same bounded service actions. Read actions return
redacted workflow/job metadata; dispatch actions require explicit repository and
ref and use request-scoped Core Secrets grants. Install/migrate/health hooks
exist; no uninstall hook is declared. Verify with
`python -m unittest discover -s apps/github-actions/tests` in the isolated environment.
