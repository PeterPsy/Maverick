# OpenRouter DeepSeek agentic certification matrix

Status date: 2026-08-19
Rollout: candidate preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==4`

## Candidate combination

| Field | Pinned value |
| --- | --- |
| Model provider | `openrouter` |
| Model | `deepseek/deepseek-v4-flash` |
| Immutable profile revision | `8` (revision `7` suspended) |
| Protocol | OpenAI-compatible streaming Chat Completions |
| API version | `v1` |
| Endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| Upstream endpoint tag | `deepinfra/fp8` |
| Effective provider identity | `DeepInfra` |
| Quantization | `fp8` |
| Context / endpoint completion limit | 1,048,576 / 65,536 tokens |
| Tool calls | one sequential function call per model step |
| Parallel request control | `parallel_tool_calls: false` on every request |
| Mixed response handling | provisional text plus one tool call is retained privately and continued |
| Reasoning levels | `minimal`, `low`, `medium`, `high`; deployed default `high` |
| Router controls | fallback off, parameters required, collection denied, ZDR required |
| Remote data classes | `public`, `workspace_internal_fake` |
| Tool handles | `core-capability:filesystem.list`, `core-capability:filesystem.read` |
| Certificate lifetime after a successful signed run | 30 days |

The dated OpenRouter endpoint catalogs listed `deepinfra/fp8` as active for
DeepSeek V4 Flash, with `tools`, `tool_choice`, `reasoning`, `max_tokens`, and
`reasoning_effort` support. It appeared in the ZDR endpoint catalog and exposed
FP8 quantization. The recorded list price was $0.09 per million input tokens
and $0.18 per million output tokens.

Every agentic request sends the sequential control and this router object
without a permissive default:

```json
{
  "parallel_tool_calls": false,
  "provider": {
    "only": ["deepinfra/fp8"],
    "allow_fallbacks": false,
    "require_parameters": true,
    "data_collection": "deny",
    "zdr": true,
    "quantizations": ["fp8"]
  }
}
```

The transport opts into OpenRouter router metadata. The codec requires the
response provider to be `DeepInfra`, then requires terminal metadata to show
the requested model, one successful attempt, and `DeepInfra` as the selected
provider. Only after those checks can the exact requested endpoint tag be
normalized as the certified upstream. Missing metadata, a different provider,
an extra attempt, or an unavailable endpoint fails closed.

Primary references:

- [DeepSeek V4 Flash model](https://openrouter.ai/deepseek/deepseek-v4-flash/api)
- [Model endpoint catalog](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints)
- [ZDR endpoint catalog](https://openrouter.ai/api/v1/endpoints/zdr)
- [Provider selection](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Zero data retention](https://openrouter.ai/docs/guides/features/zdr)
- [Router metadata](https://openrouter.ai/docs/guides/features/router-metadata)
- [Reasoning preservation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- [Tool calling](https://openrouter.ai/docs/guides/features/tool-calling)

## Evidence matrix

| Contract | Required evidence | Current certification result |
| --- | --- | --- |
| Exact request translation | deterministic payload and relaxed-control rejection fixtures | not certified |
| SSE ordering and bounds | shared bounded SSE plus OpenRouter transport fixtures | not certified |
| Effective upstream | response identity and terminal router-metadata mismatch fixtures | not certified |
| No eligible endpoint | HTTP and streamed 404 normalization fixtures | not certified |
| Tool call id/name/count | fragmented arguments, exact pairing, invalid-index classification, and true parallel-call rejection | not certified |
| Mixed text then tool | provisional narration is not finalized or duplicated; one call continues to the next step | not certified |
| Multi-step continuation | two sequential tool rounds followed by a final response | not certified |
| Filesystem discovery | bounded deterministic listing, symlink non-traversal, and workspace confinement | not certified |
| Reasoning configuration | no-tool and tool round trips at every selectable level, including deployed `high` | not certified |
| Reasoning isolation | exact private `reasoning_details` replay and public-event leakage assertions | not certified |
| Usage, generation id and price | success and decode-failure fixtures retain available telemetry and micro-USD estimate | not certified |
| Failure propagation | distinct mixed/parallel/index codes, safe public message, diagnostic reference, and nonnumeric Chat UX | not certified |
| Shared tool loop | real OpenRouter codec through deterministic hosted-loop E2E | not certified |
| Cancel/recovery/confirmation | shared hosted runtime contract suite | not certified |
| Outage after acceptance | terminal normalized failure with no blind retry | not certified |
| Revocation and egress drift | mid-step revocation and live-policy drift fixtures | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |

The table defines required coverage and does not report a completed run.
Bootstrap publishes only the candidate profile and never manufactures a
certificate. Certification requires the complete suite plus a fresh
operator-run synthetic live probe, reconfirmation of endpoint and ZDR catalogs,
an immutable result bound to source commit, suite version, adapter artifact
bundle and this matrix revision, and an Ed25519 signature from a trusted CI key.
The executable signing and publication workflow is defined in
`docs/runbooks/agentic_certification_evidence.md`.

## Fail-closed conditions

- Any model, protocol, API-version, adapter, endpoint, quantization, or upstream
  mismatch is rejected.
- `allow_fallbacks=true`, missing parameter enforcement, collection other than
  `deny`, or missing ZDR enforcement is rejected before transport.
- Missing `parallel_tool_calls: false` is a request-contract failure for the
  sequential profile.
- A 404/no-eligible-provider result is terminal and never falls back.
- Missing, expired, revoked, or digest-mismatched certificates prevent authority.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
- Function results with a different id or name are rejected before transport.
- Multiple tool calls in one response are rejected for this preview.
- A single tool call preceded by text is accepted; that text remains
  provisional, is stored with the assistant tool call in private continuation
  state, and is not duplicated in the final answer.
- Redirects, unexpected paths, non-SSE responses, oversized data, incomplete
  streams, and missing terminal routing metadata are rejected.
- Credentials, raw errors, router payloads, and reasoning details never enter
  public runtime events.
