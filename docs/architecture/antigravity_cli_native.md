# Antigravity CLI: executable Native candidate

Maverick registers `AntigravityCliNativeAdapter` through the generic Native
Agent engine contract. It does not inherit Codex code and does not use
`LegacyRuntimeBackendAgenticBridge`. The prior Gemini CLI ACP candidate is
retired; stale persisted `gemini-cli` provider metadata is filtered rather than
treated as a second integration.

The adapter targets Google's documented
[Antigravity headless stream](https://www.antigravity.google/docs/cli/headless/):
`agy --input-format stream-json --output-format stream-json`. It writes only
NDJSON `user` events and accepts the documented `init`, `step_update`, and
`result` events. The pinned candidate binary is `agy` 1.1.27 with SHA-256
`93eb2118b778a4005700b54cdd7e08b896fbe665d5ff338e38e9e53da9a091ea`.
The candidate model slug is `gemini-3.6-flash-high`; Antigravity's unknown-model
failure prevents silent fallback.

Headless authentication follows Google's documented API-key path rather than
copying a desktop login. Core resolves the workspace's provider credential
binding through the secret service. The launch builder writes a mode-`0600`
private-home `~/.gemini/antigravity-cli/settings.json` with
`modelProvider=gemini`, maps the ephemeral generic lease to
`GEMINI_API_KEY`, and omits `MAVERICK_PROVIDER_SECRET` from the child
environment. The secret value is never written to settings, workspace files,
or public events by Maverick. A missing binding or lease fails before process
creation.

## Protocol and lifecycle

- Preparation starts one supervised process, requires exactly one valid `init`,
  and verifies the conversation id, working directory, model, tool list, and
  `request-review` permission mode before publishing a prepared handle.
- Consecutive turns use one process. Each turn sends one text-only `user` event,
  consumes ordered `step_update` events, and requires exactly one terminal
  `SUCCESS` result with a nonblank response and structurally valid cumulative
  token usage.
- Agent response deltas become `runtime.output.delta`. Structured tool steps
  become started/completed/failed tool events. Tool argument values, output,
  and provider error messages remain private; public events contain only
  bounded names, byte counts, result class, and SHA-256 digests. Unknown
  sequence shapes,
  malformed or oversized lines, conversation drift, duplicate initialization,
  blank output, output/result disagreement, and invalid usage fail closed.
- Terminal usage is explicitly marked cumulative so persisted accounting
  derives per-turn deltas across process and backend restarts rather than
  double-counting a warmed conversation.
- Recovery starts a fresh confined process with `--conversation <id>` and
  requires its new `init` to return that exact id. It never uses the ambiguous
  `--continue` alias or silently creates a replacement conversation.
- Antigravity stream input does not support `control_request` or
  `control_response`; the adapter reports same-turn steering as
  `antigravity_safe_next_turn_only` instead of relabeling a later prompt.

## Containment and permissions

Launch is accepted only for sandbox-mode sessions whose workdir is the exact
workspace root. Maverick's Bubblewrap boundary exposes the workspace/runtime
write roots and declared runtime dependencies only. The CLI also receives its
documented `--sandbox` flag. Its HOME and every XDG root are private per runtime;
the process never inherits the host HOME. `--dangerously-skip-permissions` is
forbidden. `init.permission_mode` must be `request-review`, so a persisted
always-proceed setting cannot silently widen authority.

The private runtime home also means Maverick does not copy account credentials,
settings, conversations, or keyring material from an operator home. Antigravity
can use cached credentials in headless mode, but Maverick deliberately does not
inherit them. Its supported server path is the official direct Gemini API-key
mode described in Google's
[installation and authentication guide](https://www.antigravity.google/docs/cli/install).
The credential is resolved for each launch through the same platform boundary
as other credentialed runtimes. Merely finding a signed-in interactive desktop
session is not an execution credential.

Interrupt sends SIGINT to the owned process group and escalates through TERM and
KILL. Normal idle close first closes stdin, Antigravity's documented graceful
shutdown. Consumer failure, timeout, cancellation, malformed output, and active
close use hard cleanup; child-process survival is covered by the fixture.

## Event-loop ownership

Each active runtime session owns one `NativeSessionRuntime` thread and event
loop. `AntigravityCliSession` owns its process, reader task, bounded queue, and
locks on that loop. Synchronous and asynchronous Core callers marshal operations
to the same owner. The pull-driven stream advances one event only when its
consumer resumes, and explicit iterator close drains the owner on callback
failure or cancellation.

Close and interrupt fence new operations, reap the group, cancel remaining
tasks, close the loop, and join the worker thread before returning. Other
sessions retain independent owners. Only the provider conversation id survives
retirement.

## Proof and release boundary

`tests/unit/providers/test_antigravity_cli_native.py` runs the production
transport/controller against an actual local NDJSON process. It covers stream
and final output, cumulative usage, structured tool effects, soft-denied
permission effects, malformed/oversized/empty/mismatched output, identity drift,
credential delivery and redaction, private settings, incomplete tool catalogs,
concurrent preparation, interruption, recovery, and process-tree cleanup.
`test_antigravity_cli_sync_runtime.py` crosses the real synchronous Core
prepare/turn/cancel/close boundaries and verifies loop/process ownership.

Those fixtures use explicitly synthetic authority and replace only the OS
sandbox wrapper. They do not certify Antigravity. The installation remains
disabled until the bound key works from the confined runtime home, the exact
model catalog is observed, Full Workspace behavior is proven, an
independent reviewer approves the evidence, and a trusted connection
certificate is published. No Google API certificate can authorize this Native
CLI connection.
