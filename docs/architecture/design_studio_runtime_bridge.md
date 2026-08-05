# Design Studio Runtime Bridge

Status: Implemented (G3 + WP7)

Date: 2026-08-03

Decision: option B, a generic core runtime stream with an app-owned OpenDesign translator.

## Scope

This ADR freezes how the OpenDesign 0.16.1 UI delegates agent work to the
Maverick runtime. OpenDesign remains the product domain and identifier space for
projects, conversations, runs, project files, and terminal result packages.
Maverick remains authoritative for workspace identity, actor authorization,
runtime sessions and turns, providers, credentials, budgets, interrupt, audit,
and recovery.

The bridge must never give OpenDesign a provider key, Maverick cookie,
bootstrap secret, operator home, provider runtime directory, arbitrary host
path, or reusable runtime token. It must not write OpenDesign SQLite directly.
The correlation record described here is transport metadata, not a second
writable project or run catalog.

## Decision

The mandatory A-ACP-first spike proved that upstream ACP is a capable transport,
but not a safe Maverick ownership boundary at the pinned release. Option A is
therefore rejected and option B is selected automatically, as required by the
approved algorithm.

Option B has two strictly separated parts:

1. Core exposes an app-agnostic, workspace-scoped runtime submission and event
   stream. It knows only source-app ownership, runtime session/turn identities,
   ordered events, idempotency, interrupt, and recovery.
2. Design Studio owns the OpenDesign route semantics, request validation,
   correlation mapping, event translation, SSE bytes, terminal result-package
   shape, and use of OpenDesign project/conversation/file APIs.

Core source and schemas must not contain `design-studio`, `opendesign`, an
OpenDesign route, an OpenDesign event name, or an OpenDesign persistence type.

## A-ACP spike

### Pinned input

- tag: `open-design-v0.16.1`
- commit: `276b4d8e970bc143d7ad060181a89a834e3d9caf`
- package manager: `pnpm@10.33.2` through Corepack
- fixture peer:
  `apps/design-studio/tests/fixtures/rejected_a_acp_shim.py`
- machine-readable evidence:
  `apps/design-studio/service/opendesign_runtime_bridge_spike_0_16_1.json`

The fixture is deliberately not a runtime implementation. It contains no model
or tool loop and is never selected by the app. It speaks enough ACP to expose
what the exact upstream process supplies to a custom `maverick` profile.

### Executed proof

The exact checkout was installed with `pnpm install --frozen-lockfile`. The
upstream ACP and timeout suites passed 52 tests across two files. Daemon
typecheck passed. The production web export built successfully. A real daemon
was then launched with `env -i`, the custom ACP peer, a temporary data root, and
no provider secret. Playwright loaded the production OpenDesign export at the
daemon origin and initiated runs from that browser context.

Observed behavior:

| Criterion | Result | Evidence |
|---|---|---|
| UI 0.16.1 creates a real run | pass | Production page title was `Open Design`; browser-origin `POST /api/runs` returned `202`. |
| SSE before terminal | pass | The fixture marker arrived while status was `running`. |
| Correct project file | pass | `maverick-spike.html` appeared through the project files API. |
| Full five-ID correlation | fail | `session/new` contained only `cwd` and `mcpServers`; no OD run, Maverick session, or turn identity reached the peer. |
| Bidirectional idempotent cancel | pass | Two HTTP cancels returned success; ACP received one `session/cancel`; terminal package was canceled. |
| Timeout | pass | A silent prompt reached failed under the ACP stage timeout and produced a failed result package. |
| Backend restart | fail | No secure durable OD-run to Maverick-session/turn record can be established because those identifiers never meet at the ACP boundary. |
| No provider key | pass | Every peer trace had an empty sensitive-variable-name list; values were never recorded. |
| Actor attribution | fail | ACP initialize/new/prompt carry neither Maverick actor identity nor an explicit app-owned actor assertion. |
| Terminal packages | pass | Success, failure, timeout-failure, and cancel packages matched their terminal state. |
| Resume | fail | A second conversation turn used `session/new`, not `session/load`. |
| Run-scoped capability | fail | Local profiles receive static environment only; upstream run trace variables are hard-coded to agent id `amr`. |

The upstream source explains the failures:

- a local profile always inherits another registered adapter's build and stream
  behavior; it cannot declare an independent `maverick` protocol;
- inheriting Kimi supplies ACP but not `resumesSessionViaAcpLoad`;
- ACP `session/new` has `cwd` and optional MCP servers, not a run identity or
  capability descriptor;
- `OPEN_DESIGN_RUN_ID`, attempt, and session trace variables are injected only
  for the upstream `amr` id.

Pretending that the shim is Kimi, AMR, Codex, Claude, or another CLI is
forbidden. Adding a new upstream runtime definition plus spawn/env plumbing for
run identity and capability would be an invasive daemon runtime patch. It would
also leave attribution and restart ownership dependent on non-standard ACP
extensions. These are explicit option-A disqualifiers, so the algorithm selects
B without a human choice.

## Selected protocol

### Generic core request

The core submission boundary extends the existing `runtime_session_requests`
ownership model with a durable stream identity. Names below are generic and may
be used by any app:

```json
{
  "workspace_id": "workspace identifier stamped by core",
  "source_app_id": "enabled local app binding stamped by core",
  "actor_id": "authenticated actor stamped by core",
  "request_id": "caller correlation id",
  "idempotency_key": "stable app request key",
  "input_text": "runtime input",
  "project_root_capability": "opaque, short-lived core handle"
}
```

The project-root handle is not a path and is never returned to the browser or
sidecar. Core resolves it to the already authorized app/workspace root when
submitting the turn.

Submission returns:

```json
{
  "request_id": "request correlation id",
  "stream_id": "durable generic stream id",
  "runtime_session_id": "Maverick runtime session id",
  "turn_id": "Maverick turn id",
  "status": "submitted"
}
```

### Generic core event

```json
{
  "stream_id": "durable generic stream id",
  "sequence": 17,
  "event_id": "stable runtime event id",
  "event_type": "runtime.output.delta",
  "timestamp": "RFC3339 timestamp",
  "payload": {},
  "terminal": false
}
```

Required core operations are `submit`, `read_after_sequence`, `interrupt`,
`inspect`, and `recover`. Reads and interrupts require the same workspace and
source-app ownership as submission. Events are appended durably and
monotonically before delivery. The event payload is a generic Maverick runtime
payload; the core never produces an OpenDesign event.

### App-owned mapping

Design Studio persists one record per OpenDesign run under its active data
generation:

```json
{
  "workspace_id": "default",
  "od_project_id": "upstream project id",
  "od_run_id": "upstream protocol run id",
  "runtime_session_id": "Maverick session id",
  "turn_id": "Maverick turn id",
  "stream_id": "generic stream id",
  "actor_id": "authenticated Maverick actor id",
  "last_sequence": 17,
  "status": "running",
  "terminal_package_written": false
}
```

The unique key is `(workspace_id, od_run_id)`. The record contains no prompt,
credential, cookie, ticket, bearer, provider selection secret, or arbitrary
path. `od_project_id` is validated against the sidecar project API and against
the active workspace binding before runtime submission.

### App-owned event translation

The initial mapping is:

| Maverick event | OpenDesign protocol output |
|---|---|
| `runtime.turn.queued` | queued run status |
| `runtime.turn.started` | running status |
| `runtime.output.delta` | assistant text delta SSE |
| `runtime.file.changed` | project file changed event |
| `runtime.turn.completed` | succeeded terminal event and result package |
| `runtime.turn.failed` | failed terminal event and result package |
| `runtime.turn.cancelled` | canceled terminal event and result package |

Only the Design Studio translator knows this table. File events carry validated
project-relative names. Project bytes are written by the Maverick runtime into
the approved OpenDesign project root and observed through OpenDesign's file API;
neither core nor the translator accepts a browser-provided host path.

## Message sequences

### Create and incremental stream

```text
Browser/OpenDesign UI
  -> isolated sidecar origin: POST /api/runs (OpenDesign body)
Generic sidecar host
  -> declared app bridge entrypoint: method/path/body + stamped workspace/actor
Design Studio translator
  -> OpenDesign capability: validate project/conversation and reserve OD run id
  -> core: generic runtime_session_request + stable idempotency key
Core runtime
  -> translator callback: stream_id + runtime_session_id + turn_id
Design Studio translator
  -> atomic correlation record
  -> browser: 202 in OpenDesign response shape
Core runtime
  -> durable generic stream: queued, started, deltas, file events
Generic stream host
  -> Design Studio translator: ordered events after last_sequence
Design Studio translator
  -> browser: OpenDesign SSE bytes, flushed per event
  -> OpenDesign project/conversation APIs: app-owned projection updates
```

The generic route host dispatches a contract-declared app bridge; it does not
recognize `/api/runs`. The route template and all OpenDesign body/response logic
remain in the app contract and translator.

### Cancel

```text
Browser -> isolated origin: POST run cancel
Generic host -> Design Studio translator: stamped workspace/actor + OD run id
Translator -> mapping: resolve owned active turn
Translator -> core: generic interrupt(turn_id, source_app_id)
Core -> provider runtime: interrupt
Core -> generic stream: exactly one cancelled terminal event
Translator -> browser: canceled terminal package
retry -> same terminal package; no second provider interrupt
```

Queued and active turns may be canceled. A terminal turn returns its existing
terminal state. A mapping owned by another workspace or source app is denied.

### Restart and resume

```text
Core or sidecar restarts
  -> core recovers runtime session/turn and durable generic event stream
  -> Design Studio reloads correlation records from active generation
  -> translator inspects stream ownership and terminal state
  -> translator reads events after last_sequence
  -> translator writes at most one terminal package
  -> browser SSE resumes from last acknowledged sequence + 1
```

If the mapping exists but the stream does not, the run becomes a redaction-safe
recovery failure; it is never silently resubmitted. If the stream exists but a
mapping does not, it is not exposed through an OpenDesign route and is reported
for bounded cleanup. Recovery never invents a successful terminal state.

## Ownership and attribution

- Core stamps `workspace_id`, `source_app_id`, and authenticated `actor_id`;
  browser values for those fields are ignored.
- The runtime session is user-visible, workspace-scoped, and sourced by the
  enabled Design Studio local binding.
- Session creation remains denied until the app contract declares
  `permissions.runtime.create_sessions: true` and its boundary tests pass.
- Interrupt and cleanup require the same source-app ownership and their own
  declared permissions.
- OpenDesign is told that the run is app-owned and receives only a display-safe
  attribution projection. It receives no Maverick actor credential.
- Runtime provider, budget, secret delivery, tool policy, and audit remain
  entirely core-owned.

## Idempotency

Four independent keys prevent duplicated work or terminal output:

1. Runtime submission: `(workspace_id, source_app_id, request_id)`.
2. Correlation: `(workspace_id, od_run_id)`.
3. Event delivery: `(stream_id, sequence)`.
4. Terminal projection: `(workspace_id, od_run_id, terminal_event_id)`.

A retry with the same submission key returns the existing stream, session, and
turn. A different OD run cannot claim an existing stream. Terminal projection
uses compare-and-set on `terminal_package_written`; success, failure, and cancel
are mutually exclusive.

## Failure behavior

- Authorization, ownership, mapping, or capability failure: fail closed before
  runtime submission.
- Stream disconnect: retain `last_sequence`; resume without resubmitting.
- Runtime timeout: interrupt through core and translate the resulting failed or
  canceled terminal state; never leave an apparently running result package.
- Translator crash after event append: replay from the last committed sequence.
- Crash after terminal projection but before acknowledgement: idempotency returns
  the existing package.
- Sidecar unavailable: runtime operation is not silently redirected to host
  loopback or another workspace.
- Core unavailable: the sidecar cannot start or resume a Maverick-owned run on
  its own.

## Security invariants

- The sidecar sandbox receives no runtime broker socket under option B.
- The browser receives no runtime stream capability, sidecar token, path, or
  Maverick cookie.
- The app bridge is reached only through authenticated core hosting surfaces.
- Audit contains IDs, event types, status, timing, and redaction-safe error
  codes; it excludes prompt bodies, SSE text, tickets, cookies, and secrets.
- Cross-workspace read, resume, cancel, and cleanup are denied even if an ID is
  guessed.
- Core contains no OpenDesign-specific route, event, schema, or persistence
  knowledge.

## Executable proofs

The selected boundary is implemented by the generic core modules
`core/runtime/app_streams.py`, `core/apps/runtime_requests.py`,
`core/apps/runtime_root_capabilities.py`, and the ASGI stream host in
`core/api/sidecar_core_routes.py`. Design Studio owns the correlation store,
OpenDesign event translation, SSE payloads, and terminal packages in
`apps/design-studio/backend/runtime_bridge.py`. Core source contains no
OpenDesign route, identifier, event, or persistence names.

The stream record and its normalized events are durable JSON collections.
Delivery is ordered by monotonic sequence and acknowledged only after the app
translator returns the exact final sequence. SSE sends are awaited one at a
time, use no `Content-Length`, emit a bounded keepalive while idle, and resume
from `Last-Event-ID`. Replaying an already translated batch is safe and does
not create a second runtime turn or terminal package.

The project root is accepted only as an app-data-relative directory. Core
mints and immediately consumes a five-second, one-shot capability bound to the
workspace, source app, and authenticated actor; only its digest is retained.
The resolved directory must remain inside the runtime session workspace and
cannot contain a symlink. Interrupt, cleanup, stream reads, restart recovery,
and session reuse all require exact workspace and source-app ownership.

Implementation proof:

```bash
python3 -m unittest \
  tests.unit.runtime_streams.test_app_streams \
  tests.unit.api.test_app_runtime_cleanup_requests \
  tests.integration.app_hosting.test_sidecar_core_routes \
  tests.integration.recovery.test_backend_restart \
  apps.design-studio.tests.test_runtime_bridge -v
```

These tests cover durable replay after store restart, provider-neutral event
projection, real project-file change detection, one-shot capability isolation,
idempotent submission, source-app-scoped cancel and cleanup, no duplicate turn
after backend restart, unbuffered ASGI delivery, app-owned replay translation,
and success/failed/canceled result packages.

Focused repository proof:

```bash
.venv/bin/python -m unittest \
  tests.architecture.test_design_studio_runtime_bridge_proof -v
```

Pinned-source and selected-contract proof:

```bash
.venv/bin/python \
  apps/design-studio/service/verify_runtime_bridge_spike.py \
  --upstream-root /tmp/maverick-opendesign-0-16-1
```

The second command verifies the exact source digests and semantic constraints,
then proves idempotent submit, incremental delivery before terminal, file event,
restart replay after sequence, cross-workspace denial, idempotent interrupt, and
absence of credential markers in the durable journal.

Expected result: selection `B`, upstream verified, and every selected-B contract
field `true` with terminal status `canceled`.

The heavy real-daemon/browser spike is reproducible after the pinned upstream
install and web build:

```bash
node apps/design-studio/tests/spike_rejected_a_acp.mjs \
  --upstream-root /tmp/maverick-opendesign-0-16-1
```

It allocates a temporary data root and loopback port, launches the exact daemon
with a minimal environment, imports Playwright from the pinned checkout, and
removes the process group and temporary data in `finally`.

## Consequences and follow-up

- WP4 creates the generic authenticated app-to-core entrypoint/capability needed
  to invoke the bridge without exposing ports or tokens.
- WP7 implemented the generic durable runtime stream in core and the Design
  Studio translator, mapping, cancel, cleanup, recovery, and terminal packages.
- WP8 routes Design Studio CLI, MCP, reference, import, and export through the
  OpenDesign domain and removes the legacy writable project catalog.
- WP10 repeats the real UI proof under the final sandbox/origin topology and
  covers core/sidecar restart, timeout, retry, hostile workspace access, and
  full result-package behavior.

Residual risk now lies in WP8–WP10: the runtime permission and product run
routes are active, while removal of the legacy writable project catalog,
Storage result export, final full-bleed browser flow, and the complete hostile
E2E matrix remain gated there. Maverick remains experimental and local-only
under the limitations in `SECURITY.md` and production-readiness documentation.
