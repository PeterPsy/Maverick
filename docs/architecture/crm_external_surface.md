# CRM external surface

The CRM can expose its complete native interface and CRM-owned records at
`crm.apps.<installation-domain>`. This is a live application, **not** an immutable
Website Studio export. External Apps' static sandbox and publication contract do
not change.

## Small ownership boundary

- CRM owns its public HTTP adapter and settings widget. The shell prefers an
  app-owned `app.external.surfaces.settings` v1 provider and its
  `shell.app.external.surfaces` widget, otherwise it uses the unique
  shared `external.surfaces.settings` provider. No app-id checks in the shell.
- The standalone entrypoint reuses the existing App, navigation and backend
  service. There is one CRM database, not a public copy or a second implementation.
- Anonymous **read-only** access is the default. Enabling anonymous writes is a
  separate explicit setting with a warning about creation, modification and
  deletion. Disable takes effect on the next admitted request.
- A closed CRM action allowlist excludes hosting administration, callbacks,
  provider execution and background hooks. No request can select its workspace,
  app, data path, actor or dependency envelope. Mail/Calendar/Storage/Speech
  execution remains private; CRM's existing local snapshots remain visible.
- Public navigation/search does not change private workspace view preferences.
  No private PWA cache bridge, platform cookies, session tokens or Core proxy.

## Deployment and revocation

An operator-managed foreground supervisor selects one installation workspace and
CRM binding from canonical control-store state. It checks enablement and source
identity before refreshing an expiring authority projection. The public child is
confined with bubblewrap: no host network, Core stores, other app data or secrets;
only CRM code/assets, CRM data, read-only authority
and a Unix listener. Read-only mode also mounts CRM data read-only. Mode changes
replace the child before renewed serving authority. Source/deployment changes,
app disable, workspace closure and lost supervisor authority fail closed.

The installation hostname is operator configuration, never an incoming Host or
browser field. An exact HTTPS virtual host proxies only to this dedicated Unix
listener. HTTP-01 uses the existing public namespace's challenge directory;
certificate issuance/renewal is operator-owned, never triggered by requests.
Enabling a UI setting does not claim DNS, TLS or the service is already ready.

This service has independent stop/status paths and never restarts Maverick Core.
See `apps/crm/public_server/README.md` for activation and rollback. Do not describe
the CRM as online until a real HTTPS request and browser check have passed.

## Installation verification — 2026-09-20

`https://crm.apps.maverick.loopino.ai` is enabled for workspace `default`, with
anonymous **read-only** access. Its exact certificate expires 2026-12-19 and has
an independent renewal timer. Trusted HTTPS, all 20 navigation sections, reload,
desktop/mobile, denied writes/private routes, immediate suspend and supervisor
expiry/recovery were verified. The dedicated service and nginx reload did not
restart Core. The CRM Settings UI can later change access or disable this surface.

Verification also covers the real confined disposable CRM/browser, 130 CRM tests,
228 shell tests and SDK validation of both app sources. This installation result
does not imply arbitrary apps or other installations are publicly enabled.
