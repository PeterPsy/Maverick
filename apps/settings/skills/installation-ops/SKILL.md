---
name: installation-ops
description: Configure or move this standalone Maverick installation’s public address, DNS and TLS through native Core installation plans and durable jobs.
---

Use native Core installation operations for address setup and recovery. Discover
`core.installation.inspect` with `maverick core cli inspect`, then reuse the
published schemas for `plan`, `apply`, `status`, `confirm`, `retry`, `verify` and
`rollback`. The same operation ids are available over Core MCP. Full-access
platform administrator context is required.

Start with inspect: use the detected server IP, active address, worker state and
redacted Vault connection references. Read `installation_address` through Core
Developer Context for deployment or provider-specific details. Human UI lives in
Settings → Installation and `/setup`; the latter works before app frames load.

Plan the requested address with its intended public IP and a Cloudflare credential
reference. Review the exact DNS changes and external actions against the user’s
request before applying. Preserve mail and unrelated records; do not replace
nameservers or edit a zone wholesale. Initial Cloudflare delegation is a one-time
registrar action. A token needs DNS Edit and Zone Read restricted to that zone.
Store credentials through Vault; agent operations accept references, never values.

Apply when the user has authorized the requested setup or move. Follow the returned
job id with status. Waiting DNS or CA states persist their next check; avoid manual
issuance loops, polling before retry_at, or starting a second job. Retry a failed
job after correcting its reported cause. Ready requires fresh HTTPS verification,
a working app-frame/sidecar wildcard, a renewal test and the new backend address.

A provider callback registration may require a human console step. Provide its
exact URL and console link. Confirm only actions the user reports as completed;
an elapsed wait is not confirmation. Missing initial Google credentials do not
block web setup. Manual DNS mode gives instructions but cannot promise automatic
wildcard renewal; connect a supported provider before applying.

Rollback the identified job when restoration is requested. It restores only the
installation’s saved DNS/address settings and refuses to overwrite a newer change
or another actor’s DNS edits. Provider registrations require their own restoration.
Moving servers also requires the destination’s data, encryption key material,
credentials and worker to be transferred; an address job does not copy a server.
Report verified readiness and any remaining provider actions explicitly.
