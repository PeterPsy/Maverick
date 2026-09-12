# OpenRouter GLM 5.3 Flash agentic certification matrix

Status date: 2026-09-12
Matrix revision: `2026-09-12-r65-openrouter-glm-workspace-instruction-redaction-tcb55`
Rollout: Full Workspace available after exact certification and binding enablement
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==58`

## Scope

This matrix replaces the retired OpenRouter model target. Historical evidence,
profiles, certificates, traces, budgets, and catalog observations for the prior
target do not authorize this model and must not be projected onto it.

The release objective is intentionally limited to the OpenRouter API target.
Google AI Studio and Antigravity remain contained and are not part of this
promotion decision. Codex remains the active native agent and must not be
reconfigured by this work.

## Exact candidate

| Field | Pinned value |
| --- | --- |
| Model provider | `openrouter` |
| Model | `z-ai/glm-5.3-flash` |
| Resolved model | `z-ai/glm-5.3-flash-20260826` |
| Model revision policy | `provider_alias`; identity `openrouter-catalog-2026-09-12` |
| Catalog expiration | exact absence (`null`); any drift fails closed |
| Immutable profile | `agentic-profile-openrouter-glm-5-3-flash-relace-fp4@4` |
| Execution family | `maverick_agent` |
| Full Workspace contract | `codex-baseline-v21` |
| Protocol | OpenAI-compatible streaming Chat Completions v1 |
| Protocol adapter | `openrouter-chat-completions-protocol@4` |
| Runtime adapter | `maverick-hosted-tool-loop==58` |
| Harness recipe | `maverick-openrouter-chat-governed-workspace@29` |
| Provider config | `openrouter-relace-glm-5-3-flash@2` |
| Endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| Effective upstream | `Relace`; exact tag `relace` |
| Quantization | exact current catalog value `unknown` |
| Fallback | disabled |
| Required parameters | enabled |
| Provider data collection | denied |
| ZDR | required; exact endpoint must remain in the ZDR catalog |
| Context / completion | certified endpoint 1,048,576 / 131,072; profile aggregate 1,000,000 / 128,000 tokens |
| Reasoning | exact tuple `max`, `high`, `low`; default `max`; mandatory |
| Tools | every currently authorized Full Workspace Core handle; `tools` and `tool_choice` supported; sequential execution only |
| Empty tool catalog | omitted |
| Finalization | exact Core finalization instruction; `tools` and `tool_choice` omitted |
| Accounting | `openrouter-relace-glm-5-3-flash-public-list-price@2`; public list prices 90,000 / 300,000 micro-USD per million input/output tokens |
| Remote data | `public`, `workspace_internal`, `personal_data`, and `regulated_or_customer_data`; exact binding authority, no fake/public attestation |
| Always denied | `credential_or_secret`, `host_operational_metadata`, `unclassified`, and legacy `workspace_internal_fake` |
| Turn ceilings | 256 provider steps, 256 tool calls, 86,400 seconds, 16 MiB aggregate tool results; no explicit cost ceiling |
| Confirmations | disabled in the profile, matching the local Codex operating ceiling |
| Certificate lifetime | 30 days after a successful signed run |

The public OpenRouter catalogs observed on 2026-09-12 report that GLM 5.3 Flash
accepts text, image, and video input and returns text. The exact Relace
endpoint advertises `tools`, `tool_choice`, `reasoning`, `reasoning_effort`, and
`max_tokens`, supports `tool_choice.auto` and `tool_choice.none`, and appears in
the ZDR catalog with quantization reported as `unknown`. These mutable
observations grant no authority by themselves; they are revalidated immediately
before live transport.

Every request carries this non-permissive router object:

```json
{
  "provider": {
    "only": ["relace"],
    "allow_fallbacks": false,
    "require_parameters": true,
    "data_collection": "deny",
    "zdr": true,
    "quantizations": ["unknown"]
  }
}
```

## Required deterministic evidence

The suite is `maverick-openrouter-agentic-contract@65` and the certified
execution TCB is manifest 55. The exact checked-in manifest is authoritative;
this table summarizes its security objectives.

| Contract | Required result |
| --- | --- |
| Model identity | alias, resolved slug, expiration, reasoning metadata, endpoint and ZDR identities match the exact candidate |
| Request translation | exact model/routing/reasoning values; unsupported or relaxed controls rejected before transport |
| Streaming | bounded SSE ordering, terminal usage, finish reason and router metadata validated |
| Effective upstream | response provider and terminal attempt metadata prove one successful Relace route |
| Tool calls | fragmented arguments, ids, names and every contiguous index retained and validated |
| Parallel proposals | every proposal journaled and paired; no parallel execution |
| Continuation | assistant tool-call messages and matching results retained in encrypted provider-private state |
| Semantic envelope | source classifications and projection digests preserved across every provider step |
| Workspace instructions | descriptor-resolved, version-fenced content rewrites the workspace root and redacts remaining host paths; the same paths in user input remain denied |
| Tool authority | current binding, certificate, actor, TCB, egress and tool authority revalidated before effects and transport |
| Full Workspace | all required filesystem, shell/process, CLI, MCP, app and collaboration behaviors pass |
| Workspace effects | shell/process mutations commit only after exact-byte result classification is inside the live allowed class set; denied results roll back |
| Journal/recovery | no ambiguous replay after cancellation, crash or restart; exact pairing lineage retained |
| Context | bounded compaction preserves tool pairing and finalization reserve |
| Final output | durable outbox and terminal delivery remain idempotent |
| Failure paths | auth, rate limit, timeout, catalog drift, malformed stream and endpoint mismatch fail closed |
| UI governance | Settings and Chat expose the model only with current signed authority and an enabled binding |

Fixture success is necessary but is not certificate evidence. It must be
collected from one clean commit with zero skipped cases and without live
credentials in the fixture process.

## Required live probe

The operator-only probe first reads in one bounded parallel window:

1. `https://openrouter.ai/api/v1/models`;
2. the exact GLM model endpoint catalog;
3. the OpenRouter ZDR endpoint catalog.

It then performs three sequential real filesystem-list tool rounds followed by
one explicitly tool-less finalization request at each certified reasoning
effort: `max`, `high`, and `low`. A complete probe therefore contains exactly
12 provider generations and 9 governed filesystem results. Catalog reads are
not counted as generations but remain receipt-bound.

The receipt must bind:

- exact target digest and run nonce;
- main-model, endpoint, ZDR and combined catalog digests;
- resolved model and reasoning observations;
- Relace identity and capacity;
- request/result counts;
- usage and private-state events for every generation;
- absence of normalized provider errors.

A retry after an ambiguous request is forbidden. Catalog drift, missing ZDR,
changed reasoning, an ineligible endpoint, unexpected fallback, or a different
resolved slug ends the candidate run.

## Natural conformance

All 14 behavioral scenarios must pass at each of `max`, `high`, and `low` on
the same source commit, adapter digest, target digest and TCB identity:

- identity;
- repository orientation;
- nested instructions;
- explicit skill;
- targeted edit;
- shell test;
- large output;
- long process and interrupt;
- safe-next-turn steering fallback;
- attachment reference;
- finalization reserve;
- prompt-injection containment;
- restart recovery;
- next-turn continuation.

Steering, restart and next-turn scenarios include their required second turns.
Every trace must bind prompts, outputs, public events, tool invocations,
provider-step journals, source/projection/effect digests, resource accounting,
and zero absolute failure counters. Execution and post-evidence review are
separate operations; a runner cannot manufacture its own green review.

## Publication and rollout

A certificate may be signed only after the deterministic suite, exact live
probe and complete natural report all pass for the same immutable candidate.
Publication must revalidate the profile target and TCB and then read back the
stored certificate.

Rollout is OpenRouter-only and first proceeds in an isolated certification
workspace with the production credential leased ephemerally. Inputs and tool
results retain ordinary `workspace_internal` classification; the run issues no
fake/public attestation:

1. create one disabled, non-default binding;
2. verify the profile remains unavailable before feature enablement;
3. enable only the OpenRouter hosted-agent feature;
4. run one full-workspace canary, sensitive-data denial, interrupt, restart and
   rollback exercise;
5. verify zero absolute failure counters and no credential leakage;
6. enable the binding after the canary is green; changing the workspace default
   remains a separate operator choice;
7. confirm Settings and Chat show GLM 5.3 Flash and no retired target;
8. retain an immediately tested kill switch and rollback path.

Any source or TCB change after evidence collection invalidates the run. Google
and Antigravity remain disabled even if this target reaches GO.

## Primary references

- [GLM 5.3 Flash model](https://openrouter.ai/z-ai/glm-5.3-flash)
- [Main model catalog](https://openrouter.ai/api/v1/models)
- [GLM endpoint catalog](https://openrouter.ai/api/v1/models/z-ai/glm-5.3-flash/endpoints)
- [ZDR endpoint catalog](https://openrouter.ai/api/v1/endpoints/zdr)
- [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Zero data retention](https://openrouter.ai/docs/guides/features/zdr)
- [Tool calling](https://openrouter.ai/docs/guides/features/tool-calling)
