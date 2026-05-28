# Workspace Default Agent Guide

This Git repository is the workspace-local app repository for `default`.

It is not the Maverick `design` repository.

## Use The Correct Root

For Maverick core, built-in apps, app hosting, `base-shell`, `chat`, `storage`,
or any task described as work on the `design` branch, use:

```text
/home/ubuntu/projects/maverick-v3
```

That repository is the Maverick root and carries the `design` branch.

This workspace-local repository is only for workspace-owned apps under:

```text
apps/<app_id>/
```

At the time of writing, this repo contains the workspace-local CRM and Mail
apps:

```text
apps/crm/
apps/mail/
```

## App Lookup Order

General and built-in apps are more important than workspace-local apps. When a
task names an app id, check the Maverick root app source first:

```text
/home/ubuntu/projects/maverick-v3/apps/<app_id>
```

Only if that path does not exist, or if the user explicitly asks for a
workspace-local app/fork, use this repository:

```text
/home/ubuntu/projects/maverick-v3/workspaces/default/apps/<app_id>
```

For example, `chat`, `storage`, and `base-shell` must resolve to root `apps/`,
not this workspace-local repo. `crm` currently resolves here because it is a
workspace-local app.

Recommended bounded orientation commands:

```bash
git -C /home/ubuntu/projects/maverick-v3 status -sb
test -d /home/ubuntu/projects/maverick-v3/apps/<app_id> && printf '%s\n' "/home/ubuntu/projects/maverick-v3/apps/<app_id>"
test -d /home/ubuntu/projects/maverick-v3/workspaces/default/apps/<app_id> && printf '%s\n' "/home/ubuntu/projects/maverick-v3/workspaces/default/apps/<app_id>"
```

Do not use broad parent-directory searches such as `find .. -name AGENTS.md`;
they scan unrelated projects and can fail on permission-denied directories.

## Common Pitfall

If `apps/chat`, `apps/base-shell`, or `apps/storage` appears to be missing, you
are in the workspace-local repo. Do not scaffold or copy those apps here. Switch
your command `workdir` to `/home/ubuntu/projects/maverick-v3` and continue
there.

## Allowed Work Here

Use this repo for changes to workspace-local apps such as `apps/crm` and
`apps/mail`.

Do not make Maverick core or built-in app changes in this repo.
