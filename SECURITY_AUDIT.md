# Maverick v3 Security Audit

Date: 2026-04-23

## Executive Summary

Maverick v3 is not currently production-safe for sensitive data on an internet-connected host.

The core architecture has the right high-level separation goals: a headless core, workspace roots, app-owned data, platform-owned control plane, and app contracts. The implementation, however, still has bootstrap-era trust assumptions that collapse several boundaries:

- browser-origin trust is treated as enough for state-changing requests
- runtime agents receive bearer capability tokens that are not bound back to persisted session authority
- mounted app backends and lifecycle hooks execute as ordinary child Python processes of the core host
- raw secrets are persisted in plaintext JSON under `.maverick/local-state/secrets/values.json`
- app frontends are same-origin iframes without sandbox isolation
- the app event WebSocket is unauthenticated
- local control-plane state, runtime transcripts, sessions, and secrets are file-readable by other local users
- several default signing and admin secrets exist in code
- recovery automation can launch a full-access Codex process

This is fixable, but it should be treated as an architectural security rework, not a small hardening pass.

## Scope

Reviewed areas:

- architecture docs: `docs/architecture/core_architecture.md`, `docs/architecture/workspace_root_architecture.md`, `docs/architecture/app_contract_architecture.md`
- hosted HTTP/ASGI surfaces under `core/api/`
- app mounting and entrypoint execution
- runtime session, turn, WebSocket, and CLI token flows
- provider launch and sandbox code
- app SDK and app-store install surfaces
- secret store and identity persistence
- workspace filesystem helpers
- app frontends where they affect platform isolation
- deployment files under `scripts/deploy/`
- current `.maverick/local-state/` structure

This audit did not perform live exploitation, internet scanning, dependency CVE scanning, or a full JavaScript dependency audit.

## External Research Notes

The audit was extended with a focused online review of recent agentic-AI security incidents and guidance, especially OpenClaw-style systems.

Sources used:

- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- CSO Online summary of the OWASP Agentic Top 10 risk categories: https://www.csoonline.com/article/4109123/managing-agentic-ai-risk-lessons-from-the-owasp-top-10.html
- SecurityScorecard STRIKE research on exposed OpenClaw deployments: https://securityscorecard.com/blog/how-exposed-openclaw-deployments-turn-agentic-ai-into-an-attack-surface/
- Check Point advisory for OpenClaw CVE-2026-25253: https://advisories.checkpoint.com/defense/advisories/public/2026/cpai-2026-2614.html
- OpenClaw security guidance: https://docs.openclaw.ai/gateway/security
- NIST AI RMF Generative AI Profile: https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence

Local OpenClaw checkout note:

- The actual local OpenClaw checkout is `/tmp/openclaw`.
- A small Cursor MCP browser metadata directory also exists under `/home/ubuntu/.cursor/projects/tmp-openclaw`, but it is not the full OpenClaw repo.
- The local OpenClaw repo is useful because it shows how a mature agentic project documents trust boundaries, sandboxing, exec approvals, dangerous flags, plugin trust, gateway auth, security audit tooling, and incident response.

Relevant external findings:

- OWASP's Agentic Top 10 frames agents as systems that plan, act, call tools, hold memory, communicate with other agents, and operate with real identities. The listed risks include goal hijack, tool misuse, identity abuse, agentic supply chain compromise, unexpected code execution, memory/context poisoning, insecure inter-agent communication, cascading failures, human-agent trust exploitation, and rogue agents.
- SecurityScorecard reported tens of thousands of exposed OpenClaw instances and observed RCE exposure in a significant fraction of deployments. Their key point maps directly to Maverick: agentic systems are attractive because they already have access to files, APIs, messaging, cloud systems, and infrastructure.
- Check Point's OpenClaw CVE-2026-25253 advisory describes RCE through a malicious `gatewayUrl` WebSocket flow that sends a token without prompting. The important design lesson is not the exact bug; it is that UI parameters, WebSocket origins, stored tokens, and gateway control channels form a single exploit chain.
- OpenClaw's own security docs explicitly state that prompt injection is not solved by system prompts, and that hard enforcement comes from tool policy, exec approvals, sandboxing, channel allowlists, file permissions, and isolation. They also call out unsafe external-content bypass flags, opt-in sandboxing, high-risk tools such as `exec`, `browser`, `web_fetch`, and `web_search`, and disk-resident session logs.
- NIST's Generative AI profile reinforces that generative/agentic systems need lifecycle risk management, monitoring, governance, and controls beyond model behavior.

Local OpenClaw architecture lessons from `/tmp/openclaw`:

- `SECURITY.md` is explicit that OpenClaw uses a "personal assistant" trust model, not a shared multi-tenant boundary. Authenticated gateway callers are trusted operators, and shared-secret HTTP/gateway access maps to broad operator authority.
- `SECURITY.md` states that `agents.defaults.sandbox.mode` defaults to `off`; exec is host-first unless sandboxing is enabled. That is a deliberate product tradeoff for OpenClaw's single-operator model, but Maverick should not copy it for non-default workspaces.
- OpenClaw treats plugins/extensions as trusted code loaded in-process with gateway privileges. Maverick's app model should go the other direction: app code is untrusted by default unless signed, reviewed, and explicitly installed into a trusted execution profile.
- OpenClaw documents exec approvals as guardrails, not a hostile multi-tenant security boundary. It also binds approvals to exact command/cwd/env context and, where possible, direct file operand snapshots. Maverick should keep that exact-binding idea but make policy enforcement a real workspace boundary for non-default workspaces.
- OpenClaw has a `security audit` command that checks common footguns and a `--fix` mode for narrow safe remediations. Maverick needs an equivalent `maverick doctor security` gate before production use.
- OpenClaw has an inventory of `dangerous*` and `dangerously*` flags, including unsafe external content, insecure auth, disabled device auth, origin fallback, and filesystem/workspace restrictions. Maverick should represent bypasses and unsafe flags as first-class policy state rather than scattered booleans.
- OpenClaw's docs warn that workspaces are default cwd, not a hard sandbox, unless sandboxing is enabled. Maverick must avoid any ambiguity here: workspace root is a tenant boundary only if every file/tool path is enforced by the core execution broker.
- OpenClaw's security docs distinguish trigger authorization from context visibility. Maverick needs that distinction for apps, inboxes, web pages, tickets, and inter-agent messages: who can trigger an agent is separate from what untrusted context the agent can see.

## Security Posture Decision

Maverick should explicitly choose a production threat model before more feature work:

1. Platform host compromise must be considered catastrophic, but platform design should minimize paths to it.
2. Workspace code, app code, generated views, and agent output must be considered untrusted by default.
3. Browser users must not be trusted only because requests are same-origin.
4. Runtime agents must receive narrowly scoped, revocable capabilities.
5. Secrets must never be persisted in plaintext local JSON in production.
6. App installation and execution must be separated from app authoring.
7. Recovery automation must never run arbitrary full-access agents unattended on a sensitive production host.
8. Security must be policy-enforced at execution boundaries, not delegated to prompts.
9. Workspace mode must be a first-class security boundary.
10. The `default` workspace may remain a trusted full-access development workspace, but every non-default workspace must default to approval-gated execution with an explicit user-controlled bypass mode.

## Security-By-Design Target Model

Maverick should adopt "security by design" as a platform invariant:

- Every actor is a principal: browser user, runtime agent, app backend, app frontend, app installer, MCP tool, CLI call, recovery process, and external webhook.
- Every principal has explicit capabilities, not ambient authority.
- Every risky operation is classified before execution.
- Every classified operation is authorized by policy in core, not by app code, model output, or client-provided fields.
- Every bypass is explicit, scoped, time-limited, visible, and audited.
- Every untrusted input path is isolated from sensitive tool execution unless policy allows the bridge.
- Every secret access is brokered; secrets are never simply present in a readable directory, prompt, runtime home, or app process environment.
- Every external egress path is controlled because agents can exfiltrate through legitimate APIs.

The central architectural concept should be an `ExecutionPolicy` owned by the core and attached to the workspace, session, principal, and tool invocation.

Required policy dimensions:

- workspace id
- workspace security mode
- principal type and id
- runtime session id, if any
- app id, if any
- requested operation type
- target resource
- data classification
- network destination, if any
- command/process details, if any
- requested filesystem paths
- approval state
- bypass state
- expiry and revocation state

Recommended workspace modes:

- `default`: trusted development workspace. Full access can remain possible without approval because that is the intended fast local workflow. It must be visibly marked unsafe for sensitive data and should not be treated as production.
- `protected`: default for every non-default workspace. Sensitive operations require approval. Network, file, shell, browser, app install, secret access, and external API actions are capability-gated.
- `strict`: production/sensitive workspace. Destructive operations, external sends, command execution, app installation, broad filesystem access, and credential use require approval even when previously allowed. Network egress is allowlist-based.
- `break_glass`: temporary user-selected bypass for a protected or strict workspace. It must be scoped to a session or operation class, time-limited, auditable, revocable, and visually obvious.

Approval design requirements:

- Approvals must be enforced by core-side policy wrappers around every tool, CLI, MCP, app backend, and runtime bridge.
- Approval cannot be implemented as prompt text such as "ask before doing X".
- Approval records must bind the exact normalized action: command argv, cwd, file paths, network destination, API operation, recipient, attachment hash, app id, and relevant input digest.
- An approval is single-use by default. Reusable approvals require an explicit rule, a narrow matcher, and an expiry.
- If an agent changes the command, cwd, recipient, path, URL, or payload class after approval, the approval is invalid.
- Denials must be durable enough to stop retry loops.
- Approval prompts shown to users must include risk class, principal, workspace, destination, data touched, and the reason approval is required.
- Bypass decisions must be separate from approvals. "Approve this command" and "disable approvals for this workspace/session" are different actions.

Operation risk tiers:

- `read_local`: read workspace files, inspect logs, list directories.
- `write_local`: create or modify workspace files.
- `destructive_local`: delete files, overwrite large trees, migration/reset operations.
- `code_exec`: shell, Python, Node, package scripts, app lifecycle hooks, frontend builds, generated scripts.
- `network_read`: web search, web fetch, browser navigation, downloading files.
- `network_write`: HTTP POST, API mutation, uploads, web forms, browser actions that submit data.
- `external_send`: email, chat, CRM updates, calendar invites, ticket comments, social posts.
- `secret_access`: read, bind, unwrap, export, or inject secret material.
- `app_install`: install, update, enable, or build apps/plugins/MCP servers/skills.
- `identity_change`: auth settings, tokens, sessions, workspace role changes.
- `infra_change`: service restart, deploy, systemd/nginx changes, package install, firewall, database migrations.

Non-default workspace baseline:

- `code_exec`: approval required.
- `destructive_local`: approval required.
- `network_write`: approval required unless destination and operation are preapproved.
- `external_send`: approval required, with recipient and content preview.
- `secret_access`: denied to agent by default; brokered per tool where possible.
- `app_install`: admin approval required.
- `network_read`: allowed only through brokered fetch/browser tools with logging, size limits, URL allow/deny policy, download quarantine, and no ambient cookies unless explicitly granted.
- `downloaded_file_execution`: denied by default; downloaded files cannot be executed until manually approved or scanned and promoted.
- `workspace_export`: approval required if sensitive classifiers match.

This policy model is a core product requirement, not a UX nicety. Without it, Maverick cannot safely host agents that browse, download files, send API calls, or operate on sensitive data.

## Recent Agentic Attack Classes And Maverick Exposure

### 1. Agent goal hijack through direct or indirect prompt injection

Attack:

An attacker places instructions in a chat message, web page, email, PDF, repository file, issue comment, API response, or tool output. The model treats the malicious content as task instructions and changes its goal.

Current exposure:

- Maverick agents can read untrusted web content and local files.
- Runtime sessions can receive tool outputs and provider events without a hard untrusted-content boundary.
- There is no core policy that prevents a hijacked agent from escalating from reading untrusted content to using shell, filesystem, app SDK, or external API tools.
- The current design relies too much on prompt discipline and provider behavior.

Defenses:

- Mark every external content block as untrusted at the runtime context layer.
- Split "reader" agents from "actor" agents: a reader may summarize untrusted content, but cannot execute commands or send data externally.
- Require approval when an agent moves from untrusted input to side-effecting tools.
- Add URL/file/source provenance to runtime context and tool calls.
- Add prompt-injection regression tests using web pages, emails, PDFs, repo files, and tool errors.

### 2. Tool misuse and legitimate-tool exfiltration

Attack:

A compromised agent uses allowed tools for unintended outcomes: emailing secrets, uploading files, posting tokens to an API, creating a public document, or hiding data in a normal-looking payload.

Current exposure:

- App tools such as Gmail-like integrations can write externally.
- Runtime network access is currently broad.
- Secrets and transcripts are stored locally in plaintext and can be read by processes with filesystem access.
- There is no DLP-like check on tool payloads before external send.

Defenses:

- Classify tools by side effect and destination.
- Require approval for `external_send` and `network_write` in non-default workspaces.
- Add destination allowlists and deny newly observed external domains by default in strict workspaces.
- Run sensitive-data scanning on outgoing tool arguments, attachments, and browser form submissions.
- Log tool invocations with principal, source prompt, destination, payload size/classification, and approval id.

### 3. Identity and privilege abuse

Attack:

An attacker uses a low-privilege agent, browser session, app frontend, or runtime token to perform high-privilege actions through confused-deputy flows.

Current exposure:

- Runtime tokens are not bound tightly enough to persisted runtime session authority.
- `effective_mode` can be supplied by the runtime CLI request body.
- App SDK accepts browser cookies and runtime tokens across sensitive app-authoring paths.
- Same-origin app frontends can call platform APIs with user cookies.

Defenses:

- Derive principal and authority only server-side.
- Bind runtime tokens to session id, workspace id, effective mode, capabilities, expiry, and revocation.
- Move all authorization to one core service.
- Make app frontends use a scoped host bridge rather than raw platform APIs.
- Add confused-deputy tests for browser, runtime token, app backend, CLI, MCP, and WebSocket paths.

### 4. Agentic supply chain compromise

Attack:

Malicious or compromised apps, skills, MCP servers, provider plugins, package scripts, model/tool registries, or remote catalogs introduce hidden instructions, code execution, or data exfiltration.

Current exposure:

- Remote app install validates checksums from the same remote catalog, not signed provenance.
- App lifecycle hooks and backends execute as platform child processes.
- Frontend build commands may execute package scripts on the host.
- Skill/tool metadata can influence agents if injected into prompt context.

Defenses:

- Require signed app bundles and signed manifests with an offline trust root.
- Separate app authoring, review, installation, build, and execution states.
- Sandbox all app hooks, backend entrypoints, and frontend builds.
- Treat MCP/tool descriptions as untrusted metadata; sanitize and isolate them from instruction hierarchy.
- Produce an AIBOM/app bill of materials including tools, package lockfiles, entrypoints, permissions, and signatures.

### 5. Unexpected code execution

Attack:

Agent-generated code, package scripts, CLI paths, browser automation, app hooks, or downloaded files execute with unintended host privileges.

Current exposure:

- App entrypoints run through local Python subprocesses with inherited environment and repo `PYTHONPATH`.
- Recovery automation can launch full-access Codex.
- Non-default workspace approval policy does not yet exist.
- Downloaded files are not treated as quarantined untrusted artifacts.

Defenses:

- Put all code execution behind the core execution broker.
- Require approval for `code_exec` in non-default workspaces.
- Execute code in sandboxed workers with minimal mounts, no platform state, no inherited secrets, resource limits, and network policy.
- Quarantine downloads; block execution from download/cache paths.
- Never let a UI parameter, config field, or agent output become an executable path without validation and approval.

### 6. Memory and context poisoning

Attack:

Adversarial content is persisted into memory, summaries, embeddings, task history, app data, or shared agent context and later affects decisions.

Current exposure:

- Runtime events and transcripts are persisted.
- Future memory/indexing features could reuse untrusted content if not explicitly classified.
- Workspace-owned app data may be exported or re-ingested without provenance.

Defenses:

- Store provenance and trust level for every memory item.
- Keep untrusted summaries separate from trusted instructions and user preferences.
- Require promotion before untrusted content can become durable instruction-like memory.
- Add memory TTLs, review workflows, and poison-detection tests.
- Never allow retrieved memory to override system, policy, or approval decisions.

### 7. Insecure inter-agent communication

Attack:

One agent spoofs another, tampers with delegated tasks, replays messages, injects instructions into a coordination channel, or registers as a fake privileged agent.

Current exposure:

- Maverick's long-term architecture includes agent coordination, but current authorization boundaries are inconsistent.
- Runtime tokens and app events do not yet provide a complete authenticated, scoped, replay-resistant message model.

Defenses:

- Treat every agent as a separate principal with an identity key and capability set.
- Sign or authenticate inter-agent messages.
- Include sender, receiver, workspace, task id, nonce, timestamp, and allowed action scope.
- Validate message semantics before execution; "agent A said so" is never enough.
- Prevent low-privilege agents from delegating work to high-privilege agents without policy approval.

### 8. Cascading failures and runaway automation

Attack:

A compromised tool, poisoned memory, model error, outage, retry loop, or bad policy propagates across agents and workspaces, causing broad damage or cost.

Current exposure:

- There are limited global rate, concurrency, budget, and retry controls.
- Runtime events persist but observability is not yet a durable security control.
- Denied or failed operations may be retried by agents unless policy records denials.

Defenses:

- Add per-workspace budgets for tokens, tool calls, subprocesses, network egress, email sends, downloads, and runtime duration.
- Add circuit breakers for repeated denials, repeated external sends, repeated command failures, and anomalous data volume.
- Make denials and high-risk approvals visible in a security timeline.
- Add kill switches per workspace, app, agent, and tool class.

### 9. Human-agent trust exploitation

Attack:

A compromised or misleading agent persuades a user to approve risky operations, reveal credentials, disable safeguards, install a malicious app, or trust a forged summary.

Current exposure:

- The product does not yet have approval UX, risk previews, or strong audit context.
- Same-origin app frontends could present misleading UI around platform actions.
- Verbose tool output and runtime logs can contain sensitive data that a user may copy elsewhere.

Defenses:

- Approval UI must be generated by the core, not by apps or agents.
- Show exact action diffs, destination, actor, data touched, and policy reason.
- Add phishing-resistant copy: never ask users to paste secrets into chat.
- Require stronger confirmation for disabling approvals, enabling break-glass, installing apps, or exposing workspaces.
- Make dangerous states persistent and visible in the shell.

### 10. Rogue agents

Attack:

An agent continues acting against user interest due to prompt injection, objective drift, malicious app/tool influence, reward hacking, or compromised credentials while each individual action looks legitimate.

Current exposure:

- Agents can operate with broad capabilities and without a complete central policy engine.
- Runtime event logs are available but not yet security-grade detection.
- No per-agent behavioral baseline or anomaly model exists.

Defenses:

- Cap autonomous action chains in protected/strict workspaces.
- Require periodic reauthorization for long-running or high-impact tasks.
- Detect anomalies such as new destinations, unusual command families, high deletion volume, or sudden secret access.
- Support immediate agent suspension and token revocation.
- Make agent objectives explicit, versioned, and auditable.

### 11. Cross-site WebSocket hijacking and gateway token theft

Attack:

A malicious website or crafted URL causes a browser to open a WebSocket or gateway connection with ambient credentials or stored tokens. OpenClaw CVE-2026-25253 is an example class: a UI accepted a `gatewayUrl` and sent a token without prompting.

Current exposure:

- Maverick has WebSocket surfaces.
- Runtime WebSocket lacks Origin validation.
- App events WebSocket is unauthenticated.
- Browser cookies are used for authenticated platform APIs.

Defenses:

- Validate Origin on every browser WebSocket before accept.
- Authenticate and authorize every WebSocket by workspace and principal.
- Never accept gateway/backend URLs from query parameters without strict allowlists.
- Use short-lived WebSocket tickets minted by authenticated HTTP requests.
- Do not send durable tokens in WebSocket handshakes to arbitrary endpoints.

### 12. Browser-control and logged-in session abuse

Attack:

An agent with browser control acts inside logged-in sessions, reads pages, submits forms, extracts cookies via vulnerable relay paths, or follows malicious pages that manipulate automation.

Current exposure:

- Maverick includes browser-capable workflows via tools and app integrations.
- Same-origin app frontends and iframes are not strongly isolated.
- No policy currently distinguishes logged-out browsing from authenticated browser actions.

Defenses:

- Separate browser profiles by workspace and session.
- Default to logged-out browser contexts for research.
- Require approval before submitting forms, downloading files, uploading files, or using authenticated browser sessions in non-default workspaces.
- Disable arbitrary browser evaluate/JS bridge operations unless explicitly approved.
- Treat screenshots, DOM text, hidden text, and page metadata as untrusted input.

### 13. MCP and tool poisoning

Attack:

Malicious MCP servers or tools inject instructions through tool names, descriptions, schemas, error messages, or outputs. The user may never see these instructions, but the model does.

Current exposure:

- Maverick's architecture includes MCP/CLI/app tool discovery.
- Tool metadata may become part of prompt context.
- App-owned tools can be installed or generated by agents.

Defenses:

- Tool metadata is data, not instruction.
- Sanitize tool descriptions and prevent hidden instruction channels.
- Require tool manifests to declare risk class and capabilities.
- Pin and sign MCP servers; do not auto-trust remote tool catalogs.
- Show human-readable tool diffs before enabling new or changed tools.

### 14. External content bypass and unsafe hooks

Attack:

Mail, docs, webhook payloads, cron payloads, tickets, or API responses trigger agents with untrusted content, sometimes under a trusted sender identity.

Current exposure:

- App backends can ingest external service data.
- Gmail-like workflows are especially sensitive because incoming mail can carry prompt injection.
- No complete external-content classifier or hook policy exists.

Defenses:

- Every hook payload is untrusted regardless of source.
- Hook-triggered agents default to read-only/messaging-only profile.
- Any hook-to-tool escalation requires policy and often approval.
- Add source allowlists, signature verification, replay protection, and payload size limits for webhooks.

### 15. Exposed control-plane and misconfigured public deployments

Attack:

Attackers scan for exposed agent dashboards, gateways, WebSockets, app APIs, or admin panels. Once inside, they inherit the agent's integrations and local privileges.

Current exposure:

- Maverick is designed to be network-accessible behind nginx.
- Current deployment configs lack strong security headers and systemd hardening.
- Default admin/signing secrets exist if environment is not configured.

Defenses:

- Production startup must fail without explicit secure configuration.
- Bind internal services to loopback or private network by default.
- Put admin/control APIs behind strong auth, MFA where possible, CSRF, Origin checks, and rate limits.
- Provide a `maverick doctor security` command that fails on public exposure, default secrets, weak permissions, unauthenticated WebSockets, insecure cookies, and dangerous workspace modes.

### 16. Credential and session material theft

Attack:

Infostealers, malicious apps, local users, compromised subprocesses, or agents read config files, runtime homes, session logs, OAuth tokens, API keys, or provider auth files.

Current exposure:

- `.maverick/local-state` includes plaintext secrets and sessions.
- Files are world-readable by default on this host.
- Provider `auth.json` can be copied into runtime homes.
- Gmail OAuth material has browser-side handling concerns.

Defenses:

- Remove plaintext secret values from production file stores.
- Enforce `0700/0600` on local state.
- Use a dedicated service user and state root outside the repo.
- Broker provider credentials server-side instead of copying auth files.
- Rotate the currently exposed Gmail OAuth token.

### 17. Malicious downloads and file parser attacks

Attack:

Agents download archives, PDFs, Office files, images, package tarballs, or code repositories that exploit parsers, poison context, or execute during build/test.

Current exposure:

- Agents can go online and download files.
- There is no quarantine/promotion model.
- Downloaded repository/package code can be built or executed through normal developer workflows.

Defenses:

- Download into a quarantine store with no execute bit.
- Record source URL, hash, MIME, size, time, and requesting principal.
- Scan archives before extraction; prevent path traversal and symlink escapes.
- Require approval before executing or importing downloaded code.
- Fetch dependencies through locked manifests and trusted registries where possible.

### 18. Data leakage through logs, transcripts, screenshots, and exports

Attack:

Sensitive data leaks through runtime events, debug output, app stderr, screenshots, browser snapshots, workspace exports, or support bundles.

Current exposure:

- Runtime events and app errors can include sensitive payloads.
- App stderr may be returned to clients.
- Workspace export includes app data by default.

Defenses:

- Define retention and classification for every event stream.
- Redact at event creation, not only at display time.
- Encrypt sensitive transcripts or store them in protected per-workspace stores.
- Gate support bundle/export generation behind policy and scanning.

### 19. Denial-of-wallet and resource exhaustion

Attack:

Agents loop, browse recursively, download large files, spawn processes, call expensive APIs, or trigger repeated provider calls.

Current exposure:

- Core has limited global quotas and concurrency controls.
- Runtime sessions can produce large event logs.

Defenses:

- Per-workspace quotas for model spend, wall-clock, subprocess count, file bytes, network bytes, and tool calls.
- Budget approval before long-running/high-cost tasks.
- Automatic suspension on anomaly thresholds.

### 20. Security control bypass by user convenience

Attack:

Users disable approvals, enable full access, install unsigned apps, use default workspace for sensitive data, or grant broad API credentials for convenience.

Current exposure:

- `default` is intended to remain low-friction.
- The product does not yet encode safe defaults for non-default workspaces.

Defenses:

- Keep `default` fast but visibly unsafe.
- Make every non-default workspace protected by default.
- Allow bypass only as an explicit user choice with scope and TTL.
- Persist warnings and audit events for bypass use.
- Provide migration guidance: sensitive work belongs in protected/strict workspaces, never `default`.

## Critical Findings

### P0. Raw secrets are stored in plaintext local JSON

Evidence:

- `core/api/platform_state.py` wires `SecretCollections.values` to `.maverick/local-state/secrets/values.json`.
- `core/secrets/store.py` persists `{"secret_id": ..., "raw_value": ...}` directly.
- current `.maverick/local-state/secrets/values.json` contains a Gmail OAuth secret value.

Impact:

Anyone who can read the repository directory as the `ubuntu` user, a backup process, a compromised app process, a leaked archive, or another local user with read access can extract long-lived OAuth refresh tokens or future API keys.

Architectural decision:

- The JSON secret-value store must be development-only.
- Production must use a real secret backend or envelope encryption with a key not stored in the repository tree.
- The secret store contract should distinguish `SecretMetadataStore` from `SecretValueProvider`.
- Raw value retrieval should be auditable, scoped, short-lived, and impossible through generic app filesystem access.
- Existing exposed secrets must be rotated.

### P0. Control-plane state files are world-readable by default

Evidence:

- `.maverick/local-state/*` files are mode `0644`; directories are `0755`.
- Sensitive files include `identity/auth_sessions.json`, `identity/credentials.json`, `runtime/events.json`, and `secrets/values.json`.
- `core/shared/json_file_collection.py` creates parent directories and writes files without setting restrictive permissions.

Impact:

Local users or compromised local processes can read password hashes, active sessions, runtime transcripts, app state, and raw secrets.

Architectural decision:

- Production state must not live under a repo checkout with ambient user-readable permissions.
- Bootstrap file stores must enforce `0700` directories and `0600` files at creation and repair existing permissions at startup.
- Sensitive local state should move to `/var/lib/maverick3` or equivalent service-owned storage, not the source tree.
- Runtime transcript retention must be configurable because agent messages may contain secrets or business data.

### P0. Runtime API tokens are forgeable with a default signing secret and are not bound to persisted session authority

Evidence:

- `core/runtime/workspace_api_token.py` uses default secret `maverick-v3-local-runtime-api` when `MAVERICK3_RUNTIME_API_SECRET` is unset.
- Token payload contains only `workspace_id` and `runtime_session_id`.
- `core/api/runtime_cli_api.py` verifies only token signature, then trusts `effective_mode` from the request body.
- `core/api/app_sdk_api.py` accepts bearer runtime tokens without checking the session exists, is running, or has matching authority.

Impact:

If the default secret is in use, anyone who knows it can forge runtime tokens. Even with a configured secret, a token is not checked against the runtime session record. A sandboxed runtime can self-declare `full-access` in `/api/runtime/cli` and become `full_access_agent` for policy checks.

Architectural decision:

- Runtime tokens must be opaque, stored, revocable capabilities or signed claims with `aud`, `iat`, `exp`, `jti`, `workspace_id`, `session_id`, `effective_mode`, and allowed capability set.
- Every token use must load the runtime session and verify status, workspace, effective mode, source app, and expiration.
- The request body must never be trusted for caller kind or execution mode.
- Default runtime signing secrets must be removed; production startup must fail if secrets are unset.

### P0. CSRF protection is absent for cookie-authenticated state-changing APIs

Evidence:

- `core/api/session_api.py` sets `maverick3_session` as `HttpOnly; SameSite=Lax`.
- State-changing routes under `/api/admin/*`, `/api/app-store/*`, `/api/workspaces/active`, `/api/runtime/*`, `/api/apps/*/backend`, `/api/settings/workspace`, and `/api/recovery/*` rely on the cookie.
- No CSRF token, origin verification, or per-route anti-CSRF layer exists in `core/api/http.py` or `core/api/platform_host.py`.

Impact:

An authenticated admin or workspace user visiting a malicious site could be induced to submit cross-site POSTs. `SameSite=Lax` reduces but does not eliminate browser and navigation edge cases; it is not a complete CSRF model for an app with high-impact admin operations.

Architectural decision:

- Add a uniform request authentication middleware.
- Require CSRF tokens or strict Origin/Referer validation for all cookie-authenticated unsafe methods.
- Prefer `SameSite=Strict` where compatible.
- Separate browser cookies from API bearer tokens and define which routes accept each.

### P0. App backends and lifecycle hooks execute with platform process privileges

Evidence:

- `core/shared/entrypoints.py` runs app entrypoints via `subprocess.run([sys.executable, entrypoint])` with inherited environment and `PYTHONPATH` including the repository root.
- `core/api/app_mounts.py` invokes mounted app backends through this helper.
- `core/apps/lifecycle.py` runs install, migrate, export, health, and other hooks similarly.
- App entrypoints receive workspace paths, app data paths, and sometimes raw app secrets.

Impact:

Any installed app backend or hook can import core modules, read `.maverick/local-state`, inspect environment variables, access platform files, and execute as the service user. This breaks the app/core boundary. A malicious remote app bundle or compromised workspace-local app becomes platform-level code execution.

Architectural decision:

- Treat app code as untrusted unless explicitly sealed, signed, and trusted.
- Run app backends and hooks in a sandbox with only declared mounts and no repo root access.
- Do not pass raw secrets into generic app processes; use scoped secret broker calls or short-lived file descriptors/tokens.
- App backend entrypoint execution needs the same isolation standard as runtime agents, probably stronger.
- Platform-trusted built-in apps and workspace-local apps should use different execution profiles.

### P0. Same-origin app frontends are not isolated

Evidence:

- `apps/base-shell/frontend/src/components/AppFrameHost.tsx` mounts app frontends in plain iframes without `sandbox`.
- Apps are served under the same origin at `/apps/<app_id>/`.
- `core/api/app_mounts.py` does not set CSP, frame isolation, or app-specific security headers.

Impact:

Any XSS or malicious frontend code in one app runs same-origin with the shell and all other apps. It can call authenticated platform APIs using the user's cookies, read non-HttpOnly same-origin storage, manipulate parent/iframe messaging, and trigger state-changing actions.

Architectural decision:

- App frontends must not be same-origin trusted by default.
- Use per-app origins/subdomains or sandboxed iframes with a narrow postMessage bridge.
- Add Content-Security-Policy, frame-src, script-src, object-src, base-uri, form-action, and Trusted Types where practical.
- Define a host/app bridge API instead of exposing raw platform APIs to app JavaScript.

### P0. App event WebSocket is unauthenticated

Evidence:

- `core/api/app_events.py` accepts `/api/apps/events/ws` and immediately `websocket.accept`s.
- `core/api/asgi_application.py` routes `APP_EVENTS_WS_PATH` before any session resolution.
- Nginx exposes `/api/` with WebSocket upgrade headers.

Impact:

Unauthenticated clients can subscribe to app event metadata. Current event payloads are small, but this leaks workspace/app activity and creates an unauthenticated long-lived connection surface.

Architectural decision:

- All WebSockets must authenticate and authorize workspace scope before accept.
- Events must be filtered per workspace and app visibility.
- Add connection limits, idle timeout, heartbeat policy, and audit for rejected socket attempts.

### P0. Recovery watchdog can launch a full-access autonomous Codex process

Evidence:

- `scripts/rescue_backend_watchdog.py` default command is `codex exec --dangerously-bypass-approvals-and-sandbox --json -C /home/ubuntu/maverick-v3 -`.
- The prompt explicitly grants full filesystem access and asks the agent to patch and restart the backend.
- The systemd watchdog runs as `ubuntu`.

Impact:

If the watchdog is triggered under bad conditions, compromised prompt/context, poisoned repository state, or malicious app data, it can create unsupervised full-access code execution on a sensitive host.

Architectural decision:

- Disable autonomous repair in production.
- Recovery should collect diagnostics and page an operator, not patch code.
- If automated recovery remains, it must run from an immutable, signed rescue image with restricted operations and no arbitrary coding agent.

## High Findings

### P1. Default admin password and default signing secrets exist in code

Evidence:

- `core/api/platform_state.py` defaults to admin password `maverick3`.
- `core/runtime/workspace_api_token.py` defaults runtime API secret to `maverick-v3-local-runtime-api`.
- `core/api/widget_context.py` defaults widget context secret to `maverick3-dev-widget-context`.

Impact:

Misconfigured production boot can start with known credentials and known token-signing keys.

Architectural decision:

- Production mode must refuse startup without configured high-entropy secrets.
- First-boot admin creation should force one-time password provisioning or local console setup.
- Default dev secrets should be isolated behind an explicit `MAVERICK3_DEV_MODE=1`.

### P1. Session cookies are missing important attributes and session lifecycle controls

Evidence:

- `core/api/session_api.py` sets `HttpOnly` and `SameSite=Lax`, but not `Secure`.
- Session ids are raw UUIDs persisted in plaintext.
- Login does not appear to rate limit attempts, lock accounts, or rotate sessions beyond creating a new one.

Impact:

Session theft or local state compromise leads directly to account takeover. Brute-force and credential stuffing protections are absent.

Architectural decision:

- Set `Secure` on HTTPS deployments.
- Store only hashed session tokens server-side.
- Add session rotation, idle timeout, absolute timeout, revocation, and device/session management.
- Add login rate limits and audit events persisted outside in-memory observability.

### P1. Runtime event logs persist sensitive conversation and tool data

Evidence:

- `.maverick/local-state/runtime/events.json` is large and contains runtime output/tool events.
- `core/runtime/turn_submission.py` persists provider output and execution events.
- `core/providers/codex_app_server.py` emits generic raw provider payloads into runtime events for errors and steps.

Impact:

Runtime events may contain user data, files, commands, environment snippets, tool payloads, secrets pasted into chat, and business context. They are currently persisted in plaintext and readable from local files.

Architectural decision:

- Runtime events require a retention and classification model.
- Sensitive provider payloads should be redacted before persistence.
- Operators need a secure transcript export policy distinct from debug logs.
- Runtime logs should support per-workspace encryption and retention limits.

### P1. Mounted app backend responses can leak internal exceptions and filesystem paths

Evidence:

- `core/api/app_mounts.py` returns `{"error": str(error)}` for entrypoint failures.
- `core/shared/entrypoints.py` includes entrypoint path and stderr in raised errors.
- app-store and SDK APIs often return `detail: str(error)`.

Impact:

Remote authenticated users can see internal filesystem paths, command failures, contract parser details, and potentially sensitive stderr from app code.

Architectural decision:

- API responses should return stable error codes and request ids.
- Detailed traces should go to restricted server logs.
- App stderr must be size-limited and redacted.

### P1. App install trust relies mostly on remote catalog checksum, not signature or provenance

Evidence:

- `core/apps/remote_store.py` downloads remote catalog and artifact from `MAVERICK_APP_STORE_URL`.
- It validates SHA-256 from the same catalog response.
- There is no independent signature, publisher trust root, transparency log, or manual approval record.

Impact:

If the catalog endpoint, DNS, TLS termination, or app-store service is compromised, a malicious artifact and matching checksum can be served and installed.

Architectural decision:

- Remote bundles need signed manifests with offline trust roots.
- Store app install should record publisher, signature, digest, operator, target workspaces, and exact artifact.
- Consider allowlists for app ids and publishers in production.

### P1. Local app and SDK APIs allow workspace code creation from browser/runtime paths

Evidence:

- `core/api/app_sdk_api.py` allows cookie-authenticated and runtime-token authenticated SDK actions.
- Runtime token identity can create app source when `allow_custom_apps` is enabled.
- App SDK writes source under `workspaces/<workspace_id>/apps/<app_id>/`.

Impact:

Any compromised browser session, app frontend XSS, or agent runtime token can create executable app source and potentially install it if policy allows. Combined with weak app backend isolation, this can become platform code execution.

Architectural decision:

- Separate app authoring from app execution.
- Require explicit human/admin approval before newly authored workspace app code can be mounted or executed.
- Runtime-created apps should start in a non-executable draft state.
- App source writes should be attributed and versioned.

### P1. Frontend build execution can run package scripts on the host

Evidence:

- `handle_app_frontend_build` and `app_lifecycle_commands.py` expose frontend build operations.
- Build implementation was not fully audited here, but this class of operation usually invokes package manager scripts in app source.
- Sandboxed agents are allowed to trigger `app.<app_id>.frontend.build`.

Impact:

If build scripts execute in the platform host context, a workspace-local app can run arbitrary host commands during build.

Architectural decision:

- Frontend builds must run in isolated builders with no `.maverick` access and no inherited secrets.
- Builds should produce immutable artifacts after scanning and size limits.
- Agents may request builds, but the builder must enforce source, network, and filesystem policy independently.

### P1. Browser-side Gmail OAuth secret storage is unsafe

Evidence:

- `apps/gmail-app/frontend/src/api.ts` uses `sessionStorage` for client secret and access token.
- `apps/gmail-app/README.md` acknowledges browser-session OAuth secret storage.

Impact:

Same-origin XSS in any app can read these values. Browser storage is not acceptable for sensitive OAuth secrets in this platform model.

Architectural decision:

- OAuth must be server-side with PKCE/state validation and HttpOnly secure callback session.
- Browser should never handle Google client secret.
- Access tokens should be short-lived server-side leases; refresh tokens belong only in the platform secret backend.

### P1. Dynamic Views JavaScript validation is blacklist-based and bypassable

Evidence:

- `apps/dynamic-views/backend/security.py` blocks specific substrings such as `fetch(` and `window.parent`.
- Dynamic views are rendered as `srcDoc` iframes with `sandbox="allow-scripts"`.

Impact:

Blacklist filtering is not a security boundary. Obfuscated JavaScript can bypass many string checks. The current iframe sandbox reduces some damage by omitting same-origin, but the platform should not rely on substring validation as proof of safety.

Architectural decision:

- Keep dynamic views in opaque-origin sandboxed iframes.
- Remove claims that source is "approved"; call it "constrained best effort".
- Consider a no-JavaScript renderer for sensitive workspaces.
- For JavaScript views, use capability-based data injection and no network by sandbox/CSP, not string matching.

### P1. Authorization model is inconsistent between browser APIs, runtime CLI, app SDK, app backend, CLI, and MCP

Evidence:

- Browser APIs call `require_session`.
- Runtime CLI uses bearer token claims.
- App SDK accepts either session cookie or runtime token.
- App backend can write secrets through result payloads.
- CLI/MCP policies depend on caller kind/effective mode supplied by wrappers.

Impact:

Policy drift creates bypasses. The runtime CLI `effective_mode` issue is one concrete example. More are likely as surfaces grow.

Architectural decision:

- Build one central authorization service.
- Every operation should declare required principal type, workspace, role, capability, session status, and mode.
- Transport adapters should only authenticate; they should not invent authority.
- Authorization decisions should be logged and tested as contracts.

## Medium Findings

### P2. No global HTTP security middleware

Evidence:

- `core/api/http.py` only serializes responses.
- No standard security headers are applied.

Impact:

The platform lacks CSP, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame controls, request ids, and uniform error handling.

Architectural decision:

- Introduce a platform HTTP middleware layer before route handlers.
- Add security headers by default with explicit per-route exceptions.

### P2. No request size/rate/concurrency controls in core

Evidence:

- Nginx has `client_max_body_size 32m`.
- `read_json_body` reads request bodies directly.
- Runtime event and upload APIs lack per-user/workspace limits.

Impact:

Authenticated or unauthenticated surfaces can be used for resource exhaustion: large uploads, long WebSockets, runtime sessions, app backend subprocesses, and catalog downloads.

Architectural decision:

- Add per-route body limits, rate limits, session limits, app backend concurrency limits, runtime turn limits, and workspace quotas enforced in core.

### P2. App event and runtime WebSocket origin checks are missing or incomplete

Evidence:

- Runtime WebSocket authenticates cookie but does not validate Origin.
- App event WebSocket does not authenticate.

Impact:

WebSockets can be opened cross-site by browsers with ambient cookies unless server checks Origin.

Architectural decision:

- Require Origin allowlist for all browser WebSockets.
- Prefer short-lived WebSocket tokens minted by an authenticated HTTP request.

### P2. Secret aliases are predictable

Evidence:

- app secret write default alias is `{workspace_id}-{app_id}-{logical_name}`.
- Gmail uses `default-gmail-app-oauth`.

Impact:

Predictable aliases ease discovery and confusion attacks. They are not direct secret values but can help attackers target bindings.

Architectural decision:

- Use opaque secret ids for storage.
- Human aliases should be metadata only and not required for binding resolution.

### P2. Observability store is in-memory for audit events

Evidence:

- `core/api/platform_state.py` wires `MongoObservabilityStore` to `InMemoryCollection`.

Impact:

Security events disappear on restart. This weakens incident response and makes abuse harder to investigate.

Architectural decision:

- Persist audit logs to append-only storage.
- Protect audit logs from app and runtime writes.
- Add tamper-evident event ids or chained digests later.

### P2. Error and audit redaction is partial

Evidence:

- `core/observability/redaction.py` has sensitive key redaction.
- Runtime provider events and app stderr are persisted/returned in several paths.

Impact:

Sensitive data can still leak through unexpected keys, nested raw payloads, command output, or provider-specific event bodies.

Architectural decision:

- Redaction must be schema-aware at event creation points, not only generic key filtering.
- Define event schemas and explicitly mark sensitive fields.

### P2. Workspace export includes app data by default and relies on apps not storing secrets

Evidence:

- `core/workspaces/export.py` excludes logs/runtime/tmp/.maverick/cache but includes app data.
- Architecture says apps must store references, not raw values.

Impact:

If any app writes raw tokens into `data/<app_id>`, workspace exports can leak them.

Architectural decision:

- Export should scan for high-risk patterns and fail closed or warn.
- App contracts should declare secret-bearing files, excluded paths, and export classifiers.

### P2. Nginx/deployment lacks stronger headers and service hardening

Evidence:

- `scripts/deploy/nginx/maverick3.versy.ai.conf` proxies app/core traffic but sets no HSTS/CSP/security headers.
- systemd services run as `ubuntu` without hardening directives.

Impact:

Compromise of the service user likely exposes source, state, runtime, and deployments. Browser-side protections are weak.

Architectural decision:

- Use a dedicated `maverick` system user.
- Add systemd `NoNewPrivileges`, `ProtectSystem`, `PrivateTmp`, restricted writable paths, resource limits, and environment file hygiene.
- Add HSTS and security headers at nginx and/or app layer.

## Lower Findings And Hygiene

### P3. `.maverick/local-state` is gitignored but still inside the repo tree

Evidence:

- `.gitignore` excludes `.maverick/local-state/`.

Impact:

Reduces accidental commits but does not protect backups, shell history, local readers, or archive collection.

Decision:

- Treat repo checkout and mutable production state as separate roots.

### P3. Runtime sandbox allows network access

Evidence:

- `core/providers/codex_app_server.py` sets `"networkAccess": True` for workspace-write sandbox policy.

Impact:

Agents can exfiltrate workspace data if they become malicious or are prompt-injected.

Decision:

- Network should be a per-session/workspace capability, off by default for sensitive workspaces.
- Tool-level network egress should be brokered and audited.

### P3. `auth.json` is copied into runtime Codex homes

Evidence:

- `core/providers/provider_codex.py` copies selected `CODEX_RUNTIME_HOME_FILES`, including `auth.json`.

Impact:

Provider auth material is replicated into per-session runtime directories. If a workspace/runtime root is compromised, provider credentials may be exposed.

Decision:

- Avoid copying provider auth files into workspace-adjacent runtime roots.
- Use service-side provider broker credentials instead.

## Recommended Rework Program

### Phase 1: Stop Production Exposure

Do before putting sensitive data on the host.

- Disable autonomous rescue agent execution.
- Rotate existing Gmail OAuth token and any other secrets currently in `.maverick`.
- Move `.maverick/local-state` out of the repository or lock it to `0700/0600`.
- Set production-only required environment secrets and fail startup without them.
- Add `Secure` cookies and CSRF/Origin checks.
- Authenticate `/api/apps/events/ws`.
- Remove plaintext JSON secret values from production use.
- Mark `default` as unsafe/full-access development mode in product UX and documentation.
- Require approval-gated `protected` mode for every newly created non-default workspace.

### Phase 2: Establish A Trust Boundary Model

- Define principal types: browser user, runtime session, app backend, app frontend, operator, system recovery.
- Define capability tokens centrally with scopes, expiry, revocation, and persisted binding to session state.
- Replace caller-supplied `effective_mode` and `caller_kind` with server-derived authority.
- Add a single authorization engine and make all API/CLI/MCP/App SDK routes call it.
- Add contract tests for authorization decisions.
- Implement an `ExecutionPolicy` service and `ApprovalLedger`.
- Put shell, network write, external send, app install, secret access, and destructive filesystem operations behind policy gates.
- Implement explicit break-glass bypass with scope, TTL, audit, and revocation.

### Phase 3: Isolate Apps

- Run app backends and lifecycle hooks in sandboxed workers.
- Separate trusted built-in apps from untrusted workspace-local and remote apps.
- Serve app frontends from isolated origins or sandboxed iframes.
- Replace direct platform API access from apps with a host bridge and scoped app backend tokens.
- Require signed remote app bundles and explicit trust policy.

### Phase 4: Secure Runtime

- Bind runtime API tokens to persisted session status and mode.
- Make runtime network access a policy capability.
- Encrypt or restrict runtime transcripts.
- Remove copied provider auth files from runtime homes.
- Add per-workspace and per-session resource limits.

### Phase 5: Harden Operations

- Dedicated service user and state directory.
- systemd hardening.
- persistent audit store.
- request ids and centralized error handling.
- security headers and CSP.
- backup encryption and restore process.
- dependency and supply-chain scanning.

## Open Architecture Questions

- Should workspace-local apps ever be executable without human admin approval?
- Are remote catalog apps considered trusted code, untrusted code, or tiered by publisher signature?
- Should every app frontend run out-of-origin even for built-ins?
- What is the intended retention period for runtime event history and chat transcripts?
- Should sensitive workspaces disable network access by default?
- What production secret backend is acceptable: OS keyring, age/sops envelope files, Vault, cloud KMS, or database field encryption?
- Is `default` full-access mode acceptable in production, or should it become an explicit break-glass workspace?
- Should bypass be allowed per workspace permanently, or only per session/task with expiry?
- What actions are never bypassable in strict workspaces, even by an admin user?

## Bottom Line

Maverick v3 should be treated as a promising architecture with a bootstrap implementation, not as a secure production platform yet.

The most important rework is not changing file permissions; it is enforcing a coherent zero-trust boundary:

- browser code is untrusted
- app code is untrusted unless signed and explicitly trusted
- runtime agents are untrusted capability holders
- workspace files are untrusted input
- secrets are platform-controlled and never ambient filesystem data
- production recovery is operator-controlled, not autonomous code mutation

Until those decisions are implemented, this host should not contain sensitive company data, OAuth refresh tokens, customer files, or production credentials.
