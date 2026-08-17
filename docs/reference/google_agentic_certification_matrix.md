# Google Gemini agentic certification matrix

Status date: 2026-08-16  
Rollout: preview, fake-data-only  
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==3`

## Certified combination

| Field | Pinned value |
| --- | --- |
| Model provider | `google-ai-studio` |
| Model | `gemini-3.6-flash` |
| Lifecycle | stable / generally available |
| Protocol | `google-interactions` |
| API version | `v1` |
| Endpoint | `https://generativelanguage.googleapis.com/v1/interactions` |
| Continuation | stateful in production; stateless exact-history codec tested |
| Tool calls | one sequential function call per model step |
| Thought handling | summaries disabled; signatures kept provider-private |
| Remote data classes | `public`, `workspace_internal_fake` |
| Tool handles | `core-capability:filesystem.read` only |
| Certificate lifetime | 45 days |

Google documents Gemini 3.6 Flash as a stable model with a 1,048,576-token
input limit, 65,536-token output limit and function calling support. The
Interactions API supports both stateful continuation through
`previous_interaction_id` and stateless replay. In stateless mode Maverick
retains every model step, including the opaque thought signature, in encrypted
provider-private state and replays it exactly with the matching function
result.

Primary references:

- [Gemini 3.6 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash)
- [Latest Gemini models](https://ai.google.dev/gemini-api/docs/latest-model)
- [Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [Interactions function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Interactions streaming](https://ai.google.dev/gemini-api/docs/streaming)
- [Interactions API v1 reference](https://ai.google.dev/api/interactions-api-v1)

## Evidence matrix

| Contract | Evidence | Preview result |
| --- | --- | --- |
| Request translation | deterministic stateful/stateless fixtures | pass |
| SSE event ordering and model identity | strict stream decoder fixtures | pass |
| Function call id/name/count | exact pairing and parallel-call rejection tests | pass |
| Stateful continuation | previous interaction id round trip | pass |
| Stateless continuation | exact user/thought/function history replay | pass |
| Thought-signature isolation | provider-private envelope and public-event assertions | pass |
| Usage and price estimate | token usage fixtures and integer micro-USD estimator | pass |
| Shared tool loop | Google codec through the deterministic hosted-loop E2E | pass |
| Cancel/recovery/confirmation | shared hosted runtime contract suite | pass |
| Revocation and egress drift | mid-step revocation and live-policy drift fixtures | pass |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | pass |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | pass |
| Child-agent isolation | forked immutable binding and independent private state | pass |
| Live capability probe | explicit operator-only two-request synthetic probe | available, not run at bootstrap |

The packaged preview certificate is intentionally fixture-backed and records
that evidence kind. It does not claim that a live credential was exercised at
installation time. Before promotion to `available`, an operator must run the
opt-in capability probe with a Vault-delivered credential, retain its
redaction-safe result digest as platform evidence, and issue a new certificate
revision. Bootstrap and automated tests never make a live provider request.

## Fail-closed conditions

- Any model, protocol, API-version or adapter mismatch is rejected.
- A missing, expired or revoked certificate prevents authority creation.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
- Function results with a different call id or function name are rejected
  before transport.
- Multiple function calls in one response are rejected for this preview.
- Redirects, unexpected hosts, non-SSE responses, oversized requests/events and
  incomplete streams are rejected.
- Raw provider errors, thought signatures and credentials never enter public
  runtime events.
