# Default Workspace Agent Guide

All first-party Maverick source is developed on the `design` branch in:

```text
/home/ubuntu/projects/maverick-v3
```

Use that repository for core and every shared app, including CRM, Mail,
GitHub Actions, and Marta Ops. Resolve app source under root `apps/<app_id>/`.
The default workspace is runtime and tenant data, with no separate app Git
repository. Do not recreate copies of the shared app source here.

Follow the root `AGENTS.md` for implementation, verification, and Git work.
Workspace business data belongs in `data/<app_id>/` and stays outside source
commits. Explicit future custom forks may use the platform's workspace-local
project capability.

## User deliverables

Create user-requested files through Storage (`app_id: storage`) under
`storage/generated/<folder>/<file>`, unless the request is for repository source.
Verify Storage metadata/preview and return a Storage link or workspace-relative
path for user-facing deliverables.
