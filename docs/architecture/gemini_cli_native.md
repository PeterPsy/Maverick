# Gemini CLI: executable Native candidate

P5A has a second executable integration, not only a discovery declaration.
`GeminiCliNativeAdapter` registers through the generic native engine contract;
it does not inherit Codex classes or use `LegacyRuntimeBackendAgenticBridge`.
Its controller delegates lifecycle operations to the ACP engine, which owns
its supervised protocol process rather than exposing raw Core process handles.

The implementation targets Gemini CLI's
[ACP NDJSON interface](https://github.com/google-gemini/gemini-cli/tree/main/packages/cli/src/acp):
`gemini --acp`, ACP version 1 initialization, `session/new`, `session/load`,
`session/prompt`, `session/update`, and `session/cancel`. Load support is checked
before resuming; unsupported recovery never silently creates another session.
See [ACP session setup](https://agentclientprotocol.com/protocol/v1/session-setup).
Gemini's ACP `prompt()` replaces the pending prompt in the same session;
Maverick first waits for a structured cancellation response, then starts the
replacement with an update-generation fence. This prevents old queued chunks
from contaminating the replacement final and retains one terminal result. See the
[Gemini session implementation](https://github.com/google-gemini/gemini-cli/blob/main/packages/cli/src/acp/acpSession.ts).

## Containment and lifecycle

- Launch requires sandbox mode and a workdir inside the workspace. The existing
  bubblewrap launcher exposes only workspace/runtime write roots and declared
  read-only runtime dependencies, with a private Gemini home and allowlisted env.
- The transport uses pipes, bounded JSON frames/queues and request deadlines.
  It never parses human terminal output. Malformed streams, blank successful
  output, or effects outside the workspace fail closed and reap the process.
- Native tool updates are projected as structured effect events. Client-side
  filesystem and terminal capabilities are not advertised. Permission requests
  are explicitly denied; there is no fabricated approval or silent auto-accept.
- Interrupt sends protocol cancellation and terminates the owned process group.
  Cleanup also kills surviving group children. Recovery starts another confined
  process and loads the same persisted provider session id.
- Concurrent connects share one process; startup cancellation fences publication
  of a late connection and reaps an unfinished handshake. A second turn cannot
  enter during connection setup. Steering and terminal publication are serialized.

## Event-loop ownership at Core entrypoints

The synchronous Core bridge intentionally runs short-lived caller loops. Gemini
does not attach a persistent ACP connection to those loops. Each active session
has one supervised `NativeAcpRuntime` thread/loop; its `GeminiAcpSession` owns
the process, reader, pending RPC futures, queues, and locks on that loop only.
Preparation, consecutive turns, steering, interrupt and recovery marshal onto
that owner from either synchronous workers or asynchronous callers. Registration
and health checks do not start a session worker, and prepared handles are opaque
outside the adapter.

Streaming uses a bounded, pull-driven handoff. One task advances the generator
for the whole turn, and the next event is not requested until the consumer resumes.
This preserves task-local timeout scopes and the steering fence at yielded events,
without moving asyncio queues or futures between loops. Core and the native
controller explicitly close owned event iterators on consumer failure/cancellation;
cleanup cannot be deferred to caller-loop shutdown or generator garbage collection.

Close/interrupt fence new operations, reap the process group, cancel and drain
pending tasks/generators, close the owner loop and join its thread before returning.
Cleanup is idempotent and remains fenced even if the cleanup caller is cancelled
repeatedly. Other sessions retain their independent loops. Only the provider
session id survives retirement, so subsequent recovery loads the same session on
a fresh owner rather than reusing dead asyncio objects or silently creating a
different upstream conversation.

## Proof boundary and NO-GO

`tests/unit/providers/test_gemini_cli_native.py` runs an actual local ACP fixture
process through the production transport/controller. It covers streaming/final
output, replacement steering, interrupt, load/resume, denied permissions,
observed tool effects, malformed/empty/out-of-bound output, concurrent connect,
startup interruption, and timeout cleanup of a process tree. The fixture replaces the OS sandbox
wrapper only; it does not mock RPC calls or the engine lifecycle.

The fixture also executes a successful turn and a loaded continuation through
the real Core `execute_agentic_runtime_turn`, with explicitly synthetic test
authority (not an installed certificate). Events start at ordinal 1 and increase
strictly per turn. Request-sent and accepted callbacks precede output; exactly
one nonblank final is followed by `provider.execution.completed` with exit code
0. A final text delta alone is never treated as successful execution.

`test_gemini_cli_sync_runtime.py` additionally crosses the real synchronous
`prepare_agentic_runtime`, `execute_runtime_turn`, `cancel_agentic_runtime` and
`close_agentic_runtime` boundaries on the same controller. It verifies two turns
without reconnecting, explicit preparation, interrupt during preparation and an
active turn, recovery/load, steering, idle/active cleanup, and a failing Core
consumer callback. Both a caller with no loop and one already running a loop are
covered. Process reaping, reader completion, owner-loop closure and joined worker
threads are asserted, not inferred from a successful adapter return alone.

This is a framework/lifecycle proof, **not live Gemini certification**. No Gemini
CLI executable, remote credentials, provider requests, runtime-artifact approval,
Full Workspace certificate, or enabled workspace binding is installed by
registration or these tests. Real sandbox/effect, context/skills, credential,
provider-version, and model behavior still require certification before release.
The candidate remains clamped to disabled even if persisted metadata requests
activation. Google/OpenRouter remote agents remain NO-GO.
