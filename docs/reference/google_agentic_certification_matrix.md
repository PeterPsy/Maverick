# Google Gemini agentic certification matrix

Status date: 2026-08-16  
Rollout: candidate preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==3`

## Candidate combination

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
| Certificate lifetime after a successful signed run | 45 days |

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

| Contract | Required evidence | Current certification result |
| --- | --- | --- |
| Request translation | deterministic stateful/stateless fixtures | not certified |
| SSE event ordering and model identity | strict stream decoder fixtures | not certified |
| Function call id/name/count | exact pairing and parallel-call rejection tests | not certified |
| Stateful continuation | previous interaction id round trip | not certified |
| Stateless continuation | exact user/thought/function history replay | not certified |
| Thought-signature isolation | provider-private envelope and public-event assertions | not certified |
| Usage and price estimate | token usage fixtures and integer micro-USD estimator | not certified |
| Shared tool loop | Google codec through the deterministic hosted-loop E2E | not certified |
| Cancel/recovery/confirmation | shared hosted runtime contract suite | not certified |
| Revocation and egress drift | mid-step revocation and live-policy drift fixtures | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |
| Live capability probe | explicit operator-only two-request synthetic probe | available, not run at bootstrap |

The table lists the required suite coverage; it is not evidence that the suite
ran. Bootstrap publishes only the candidate profile and never manufactures a
certificate. A certification pipeline must execute the complete suite and the
operator-only synthetic live probe, bind the result to the source commit,
suite version, adapter artifact bundle and this matrix revision, and sign the
completed run. Only that verified artifact may be used to issue a certificate.

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
