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
steering uses this behavior and retains one Maverick terminal result. See the
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

## Proof boundary and NO-GO

`tests/unit/providers/test_gemini_cli_native.py` runs an actual local ACP fixture
process through the production transport/controller. It covers streaming/final
output, replacement steering, interrupt, load/resume, denied permissions,
observed tool effects, malformed/empty/out-of-bound output, concurrent connect,
startup interruption, and timeout cleanup of a process tree. The fixture replaces the OS sandbox
wrapper only; it does not mock RPC calls or the engine lifecycle.

This is a framework/lifecycle proof, **not live Gemini certification**. No Gemini
CLI executable, remote credentials, provider requests, runtime-artifact approval,
Full Workspace certificate, or enabled workspace binding is installed by
registration or these tests. Real sandbox/effect, context/skills, credential,
provider-version, and model behavior still require certification before release.
The candidate remains clamped to disabled even if persisted metadata requests
activation. Google/OpenRouter remote agents remain NO-GO.
