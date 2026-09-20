# Antigravity CLI Native Agent Contract

Antigravity is an optional `native_agent` candidate. It is independent from the
Google hosted API integration and uses its own cached OAuth identity.

## Structured runtime

The integration uses persistent `agy` sessions with `--input-format stream-json`
and `--output-format stream-json`. Core owns launch, process supervision, bounded NDJSON parsing,
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
Discovery and runtime-health failures only disable the live registry projection;
they must not overwrite the operator's persisted activation. A later successful
refresh restores availability for an already enabled provider. An explicitly
disabled provider remains disabled after recovery. If an older version already
overwrote the saved activation during a failed refresh, an operator can restore
it through `core.providers.native.activate`, or a signed-in platform admin can
press `Enable Antigravity` in Settings → Models. The latter calls
`POST /api/providers/native/activate` with the explicit
`native-runtime-reviewed` confirmation, using the same activation service and
runtime/catalog validation as the CLI. It requires a human admin session cookie;
runtime bearer tokens do not authorize this action. Workspace model selections
are preserved, and Settings reloads the current availability after activation.

## Workspace context and effects

Core sets both the process cwd and `--add-dir` to the active workspace. Cwd
alone does not register a workspace in Antigravity's private profile.
Sandbox sessions keep a writable workspace inside the outer sandbox;
full-access sessions use the native permission bypass and host filesystem.
The provider home remains private in both modes.

Codex discovers workspace instructions and its materialized skill catalog
natively. Core supplies those same sources explicitly to Antigravity before
each user input: workspace paths and execution mode, the complete applicable
`AGENTS.md` chain, the session's agent instructions and the available skill
catalog. App references, attachments and governed context retain the shared
turn-input projection. This context is transient and is refreshed on later
turns, including resumed conversations.

Implicit sessions use the same enabled, session-allowed skill resolver as
Codex; explicit sessions use the invoked set. Skills are copied to a read-only
session subtree in sandbox mode; a skill digest change retires the process
before reuse. The runtime-token `maverick` wrapper exposes the same governed
Core and app CLI/MCP surfaces as other native runtimes.

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
successful operational tests. Google AI Studio is not published as a separate
API-agent choice, and Google API credentials are never accepted on this path.

## Known boundary

Antigravity owns an internal native tool loop. In sandbox mode its filesystem
boundary is the outer sandbox; full-access mode deliberately grants host access.
Native workspace edits do not pass through the Core mutation bridge, while calls
through the Maverick CLI retain Core authorization. Maverick does not claim every
native read or write as a Core tool event. Loss of the structured protocol,
required execution boundary, process supervision or current catalog identity
makes the runtime unavailable.
