# Per-app settings in the shell

The settings gear beside the workspace selector opens settings for the **current
app**, not platform administration. Workspace creation belongs exclusively to the
Settings app; the shell selector only switches existing workspaces.

Base Shell owns the dialog, current app/workspace/session scope, sidebar pinning
(through App Store; fixed shortcuts excluded and at least one rail app retained)
and two sections: app settings and external surfaces. App-specific settings stay
app-owned through an optional existing iframe widget contract:
`host=base-shell`, `content_kind=shell.app.settings`, exact active owner. An app
without such a widget has no invented preferences. The ordinary Settings app and
its platform/workspace administration remain unchanged.

The external section first selects the active app itself if it provides
`app.external.surfaces.settings` v1. This capability manages only its own live
surfaces through the same widget content kind; it is not a global provider for
other apps. Otherwise the section discovers the unique enabled provider of
`external.surfaces.settings` v1 and its `shell.app.external.surfaces` widget.
External Apps supplies that supporting surface; the shell does not import its
code, catalog, publication actions or app id. The widget receives only the selected
app id/name in explicit context and uses its owner's authenticated backend. This
context is a UI filter, never a substitute for Core actor/workspace authority.
All scoped catalog, plan and mutation lookups recheck the source app identity.

The initial public capability remains `external.static-bundle.export` v1, with
immutable build plans, exact human approval and suspend/rollback. Unsupported apps
show an explicit unavailable state, not a switch that exposes private app frames,
Core APIs or user data. The selected exporter still comes from Core dependency
resolution. Settings do not make authenticated applications anonymously public
implicitly. CRM explicitly implements its own live surface and opt-in access
controls; see [`crm_external_surface.md`](crm_external_surface.md). This does not
relax the static publisher or grant public callers access to Core.

Dialog state is memory-only. App/workspace/session transitions discard the old
scope, and widget frames are separately authenticated origins. Native dialog
focus handling, Escape, loading/error/empty states and mobile layout are required.
No new settings database or generic configuration-schema framework is introduced.
Public URL and TLS policy remain in `external_apps_v1.md`.

Widgets may emit `maverick.widget.ready` with their owner and widget ids after
installing the context listener. The shell replies only to the exact registered
iframe/source/origin and sends current context/theme; readiness grants no new
capability. General widgets use their own backend and existing settings models.

## Shell widget launch and failure handling

A supporting app’s declared widget is not a launchable full-app frontend. Shell
widget launch uses the existing `/api/app-frames/browser-launch` endpoint, with
the exact declared widget document and a signed context fragment. Core checks the
current actor, workspace, owner, widget, host and content kind, and binds the
existing widget identity fields into the browser ticket/session. Full-app launch
still requires a launchable frontend; supporting role is not a way around it.
Current visibility, enablement and widget declaration are checked again during
bootstrap and requests. Nested widget launch retains its separate exact-parent
policy. There are no new anonymous routes or control-store schemas.

The shell displays launch errors and a manual retry instead of hiding rejection
behind an infinite spinner. A frame that never loads times out after 60 seconds;
retry remounts only that widget and does not replay app mutations. Deploying the
Core launch-policy fix requires the normal governed backend restart. A frontend
build alone cannot update policy already loaded by a running Core.
