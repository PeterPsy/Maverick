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

The external section discovers the enabled provider of
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
resolution. Settings do not make authenticated applications anonymously public.

Dialog state is memory-only. App/workspace/session transitions discard the old
scope, and widget frames are separately authenticated origins. Native dialog
focus handling, Escape, loading/error/empty states and mobile layout are required.
No Core restart, new settings database or generic configuration-schema framework
is introduced. Public URL and TLS policy remain in `external_apps_v1.md`.

Widgets may emit `maverick.widget.ready` with their owner and widget ids after
installing the context listener. The shell replies only to the exact registered
iframe/source/origin and sends current context/theme; readiness grants no new
capability. General widgets use their own backend and existing settings models.
