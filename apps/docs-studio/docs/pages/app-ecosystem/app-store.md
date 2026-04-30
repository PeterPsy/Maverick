# App Store

The App Store is itself an app, but installation and source registration remain core-owned app-hosting operations.

## App Store shows

- remote catalog apps
- installation-level server app sources
- workspace-local projects
- current workspace installation state
- invalid local projects with validation errors

## Core-owned operations

| Operation | Endpoint or surface |
| --- | --- |
| remote catalog read | `/api/app-store/apps` |
| server app source read | `/api/app-store/server-apps` |
| workspace install state | `/api/app-store/installations` |
| remote install | `/api/app-store/install` |
| local registration | `/api/app-store/register-local` |
| local install | `/api/app-store/install-local` |
| uninstall binding | `/api/app-store/uninstall` |

## Safety model

Uninstall removes the workspace binding by default. Complete deletion is narrower and applies to workspace-local projects where the workspace owns the source.
