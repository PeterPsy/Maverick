# Antigravity CLI Native Agent Contract

Antigravity is an optional `native_agent` candidate. It is independent from the
Google hosted API integration and uses its own cached OAuth identity.

## Structured runtime

The integration uses the persistent `agy --experimental-acp` structured stream
protocol. Core owns launch, process supervision, bounded NDJSON parsing,
interrupt, recovery, cleanup and final-output validation. Human terminal or ANSI
scraping is not accepted.

## Private identity and home

The host operator provisions the cached Antigravity OAuth identity. Core copies
only required identity material into a session-private
`MAVERICK_ANTIGRAVITY_HOME`, replaces settings with controlled values and does
not expose the host HOME. Public events and app/browser APIs never contain OAuth
material.

Catalog discovery uses another ephemeral confined home. Failed authentication,
binary drift or malformed catalog output grants no model availability.

## Workspace effects

The outer sandbox mounts the workspace read-only to native tools and makes only
the private runtime subtree writable. Confirmed workspace mutations cross Core
through the runtime-token `maverick` CLI/MCP wrapper. Selected skills are copied
to a read-only session subtree; a skill digest change retires the process before
reuse.

## Direct profile and admission

The native installation contract declares engine, adapter, protocol, recipe,
effects, model-provider connection and Full Workspace identity. Model projections
directly declare capabilities and reasoning choices.

Admission requires an enabled provider/profile/workspace binding, installed and
healthy runtime, current authenticated model catalog, exact contract identity,
actor/policy approval and normal containment checks. There is no separate
issuance or expiry lifecycle.

Antigravity remains disabled by default until an operator explicitly enables the
provider and workspace profile after reviewing the current runtime contract and
successful operational tests. Enabling it does not enable Google AI Studio and
Google API credentials are never accepted on this path.

## Known boundary

Antigravity owns an internal native tool loop, so Maverick relies on the outer
sandbox and governed mutation bridge rather than claiming every internal read as
a Core tool event. Any loss of structured protocol, confinement, process
supervision or current catalog identity makes the runtime unavailable.
