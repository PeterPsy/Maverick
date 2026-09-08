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

Headless authentication follows Google's documented cached-login path. An
operator signs in to Antigravity outside a tenant runtime and provisions only
the resulting `antigravity-oauth-token` into a Core-owned mode-`0700` source
directory selected by `MAVERICK_ANTIGRAVITY_HOME`; the token itself must be a
single-owner, single-link mode-`0600` regular file. Each launch atomically
copies that one identity file into the session-private home and writes its own
controlled settings containing only `enableTerminalSandbox=true` and
`toolPermission=request-review`. The process receives neither
`GEMINI_API_KEY` nor `MAVERICK_PROVIDER_SECRET`. A provider credential binding,
API-key lease, symlink, hard link, wrong owner, permissive mode, missing token,
or changing source fails before process creation. Google AI Studio's API key
remains a separate credential used only by the Maverick Agent API provider.

Catalog discovery uses a fresh private copy of the same OAuth identity, the
exact reviewed binary, an allowlisted environment, and a Bubblewrap filesystem
boundary. Only a successful bounded `agy models` response matching the strict
two-column catalog contract publishes a five-minute availability snapshot.
Malformed, duplicate, oversized, unauthenticated, or binary-drifted discovery
publishes no native model authority. Persisted and fallback model labels remain
diagnostic metadata and cannot make the candidate selectable.

## Operator provisioning

The hosted Linux service uses
`/var/lib/maverick/provider-homes/antigravity-cli` as the private source and
sets that path through a systemd `MAVERICK_ANTIGRAVITY_HOME` environment
override. Both the directory and copied token are owned by the Core service
account with modes `0700` and `0600`. Provisioning copies the already cached
login file without printing it; an interactive authorization code is neither a
runtime token nor valid configuration. After login rotation, the operator must
replace the source file atomically and restart or explicitly refresh Core so a
new catalog epoch is observed. No tenant workspace may be used as the source.

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
  double-counting a warmed conversation. Antigravity reports cache reads
  independently from uncached input, so cumulative `cache_read_tokens` may be
  greater than `input_tokens`; `total_tokens` remains the exact sum of input
  and output, and thinking remains a subset of output.
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

The private runtime home means Maverick never mounts or inherits the operator
home. It copies only the explicitly provisioned cached OAuth identity; operator
settings, conversations, project history, keyring material, and unrelated
Google credentials are excluded. Refreshing or revoking that operator login is
an operational credential action outside tenant execution. The login behavior
and remote/headless flow are documented in Google's
[installation and authentication guide](https://www.antigravity.google/docs/cli/install)
and [headless guide](https://www.antigravity.google/docs/cli/headless/).

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
OAuth boundary rejection and redaction, private settings, incomplete tool catalogs,
concurrent preparation, interruption, recovery, and process-tree cleanup.
`test_antigravity_cli_sync_runtime.py` crosses the real synchronous Core
prepare/turn/cancel/close boundaries and verifies loop/process ownership.
`test_antigravity_cli_runtime_home.py` covers source and destination filesystem
fences, while `test_antigravity_cli_discovery.py` covers authenticated private
catalog discovery, exact-binary gating, and disabled publication.

Those fixtures use explicitly synthetic authority and replace only the OS
sandbox wrapper. They do not certify Antigravity. The installation remains
disabled until the provisioned OAuth profile works from the confined runtime home, the exact
model catalog is observed, Full Workspace behavior is proven, an
independent reviewer approves the evidence, and a trusted connection
certificate is published. No Google API certificate can authorize this Native
CLI connection.
