# OpenRouter DeepSeek agentic certification matrix

Status date: 2026-08-17  
Rollout: preview, fake-data-only  
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==3`

## Certified combination

| Field | Pinned value |
| --- | --- |
| Model provider | `openrouter` |
| Model | `deepseek/deepseek-v4-flash` |
| Protocol | OpenAI-compatible streaming Chat Completions |
| API version | `v1` |
| Endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| Upstream endpoint tag | `deepinfra/fp8` |
| Effective provider identity | `DeepInfra` |
| Quantization | `fp8` |
| Context / endpoint completion limit | 1,048,576 / 65,536 tokens |
| Tool calls | one sequential function call per model step |
| Router controls | fallback off, parameters required, collection denied, ZDR required |
| Remote data classes | `public`, `workspace_internal_fake` |
| Tool handles | `core-capability:filesystem.read` only |
| Certificate lifetime | 30 days |

The dated OpenRouter endpoint catalogs listed `deepinfra/fp8` as active for
DeepSeek V4 Flash, with `tools`, `tool_choice`, `reasoning`, `max_tokens`, and
`reasoning_effort` support. It appeared in the ZDR endpoint catalog and exposed
FP8 quantization. The recorded list price was $0.09 per million input tokens
and $0.18 per million output tokens.

Every agentic request sends this router object without a permissive default:

```json
{
  "only": ["deepinfra/fp8"],
  "allow_fallbacks": false,
  "require_parameters": true,
  "data_collection": "deny",
  "zdr": true,
  "quantizations": ["fp8"]
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

| Contract | Evidence | Preview result |
| --- | --- | --- |
| Exact request translation | deterministic payload and relaxed-control rejection fixtures | pass |
| SSE ordering and bounds | shared bounded SSE plus OpenRouter transport fixtures | pass |
| Effective upstream | response identity and terminal router-metadata mismatch fixtures | pass |
| No eligible endpoint | HTTP and streamed 404 normalization fixtures | pass |
| Tool call id/name/count | fragmented arguments, exact pairing, and parallel-call rejection | pass |
| Multi-step continuation | two sequential tool rounds followed by a final response | pass |
| Reasoning isolation | exact private `reasoning_details` replay and public-event leakage assertions | pass |
| Usage and price estimate | token fixtures and integer micro-USD estimator | pass |
| Shared tool loop | real OpenRouter codec through deterministic hosted-loop E2E | pass |
| Cancel/recovery/confirmation | shared hosted runtime contract suite | pass |
| Outage after acceptance | terminal normalized failure with no blind retry | pass |
| Revocation and egress drift | mid-step revocation and live-policy drift fixtures | pass |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | pass |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | pass |
| Child-agent isolation | forked immutable binding and independent private state | pass |

The packaged preview certificate is fixture-backed. Bootstrap never calls a
remote provider and does not claim that an installation credential was tested.
Promotion requires a fresh operator-run synthetic probe, retained redaction-safe
evidence, reconfirmation of the endpoint and ZDR catalogs, and a new certificate
revision.

## Fail-closed conditions

- Any model, protocol, API-version, adapter, endpoint, quantization, or upstream
  mismatch is rejected.
- `allow_fallbacks=true`, missing parameter enforcement, collection other than
  `deny`, or missing ZDR enforcement is rejected before transport.
- A 404/no-eligible-provider result is terminal and never falls back.
- Missing, expired, revoked, or digest-mismatched certificates prevent authority.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
- Function results with a different id or name are rejected before transport.
- Multiple tool calls in one response are rejected for this preview.
- Redirects, unexpected paths, non-SSE responses, oversized data, incomplete
  streams, and missing terminal routing metadata are rejected.
- Credentials, raw errors, router payloads, and reasoning details never enter
  public runtime events.
