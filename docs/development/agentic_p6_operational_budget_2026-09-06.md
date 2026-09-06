# P6 operational budget checkpoint — 2026-09-06

**Not a P6 completion, live receipt, security approval or release.** The verified
historical P6-D source remains `5a7ca45a`; the new worker changes require a new
candidate freeze and complete conformance before certification.

## Operator authorization and actual state

The user superseded the proposed 100 USD budget with **at most 5 USD total on
OpenRouter and Google free tier only**, and authorized a separate review agent.
No model generation, credential resolution, top-up, billing upgrade, backend
restart or certificate/binding activation was performed in this checkpoint.

One private operator job was initialized, outside the repository and workspace:
`/var/tmp/maverick/maverick-p6-operator-dd5hrvqq`. Its local locator is
`/tmp/maverick-p6-operational-job-path`; all subsequent workers must use this
same job, never recreate a ledger to regain budget. It contains no provider
credential. Initial status:

| Provider | Job ceiling | Requests | Pacing | Reserved / generations |
|---|---|---|---|---|
| OpenRouter | USD 4.50, with USD 0.50 headroom below user cap | 200 | 1 second | USD 0 / 0 |
| Google | Free-tier project, as declared by operator | 80 | 15 seconds | USD 0 / 0 |

The authorization document SHA-256 is
`4d82ecb1cdaf82365691e7b2fb5822aeb427dc5ef651980d04a4261ee1d28fb0`;
the immutable budget policy digest is
`21d0fda1023d3fdca258d1693214303d1a4afbb51ffe7ec6bbb00c07e1ec2cf8`.
Free-tier status and remaining provider credit/quota have **not** been verified
through an authenticated provider observation. The ledger reports Google's
list-price exposure separately; its zero paid reservation is not billing proof.

## Implemented and tested

- Operator-created SQLite ledger, private file/directory checks and fixed
  policy digest; missing/corrupt/shared/symlinked files fail closed.
- Atomic aggregate cost/quota reservation before transport across connections,
  workers and restarts. Actual child-process death after reservation retains
  the charge. No reset/refund/resume API exists.
- Cross-worker pacing before egress, not a provider retry. Stream/transport
  failures durably stop the provider; cancellation retains the reservation
  without preventing an independently authorized cancellation/next-turn test.
  Follow-up regression covers nested Google terminal failure statuses and
  OpenRouter `finish_reason: error`, not only a top-level SSE error field.
- Both direct protocol probes require the ledger. Live collection validates
  and forwards its path/digest before running the costly fixture step.
- The P6 budget CLI rejects an OpenRouter ceiling over USD 5 or Google pacing
  below 15 seconds. It does not resolve secrets or grant runtime authority.

Command (all transports simulated, no credential injected):

```bash
python3 -W error::ResourceWarning -m unittest \
  tests.unit.providers.test_certification_budget_ledger \
  tests.unit.providers.test_certification_probe_budget \
  tests.unit.scripts.test_google_probe_catalog_receipt \
  tests.unit.scripts.test_openrouter_agentic_probe \
  tests.unit.scripts.test_agentic_probe_fail_closed \
  tests.unit.scripts.test_agentic_certification_runner -q
```

Result: **28 tests, zero failures/errors**. Expected argparse rejection messages
are negative tests. The unused-import check and scoped whitespace check pass.
This is focused worker evidence, not a rerun of the 635/644 canonical suites.
The nested-terminal follow-up passed the 16 ledger/transport tests separately.

## Public catalog diagnostic, not authenticated live evidence

At `2026-09-06T14:00:15.578253Z`, a credential-free GET of the official
[OpenRouter model endpoint catalog](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints)
returned DeepInfra FP8 with 1,048,576 context, 65,536 completion capacity and
USD 0.09/0.18 per million input/output tokens, matching the configured prices.
However, its `supports_tool_choice.none` is **false**. The existing explicit-none
catalog contract must reject that record. Do not relabel it supported or remove
the check solely to obtain success. A tools-omitted finalization design, if
adopted, needs an explicit protocol-contract change, negative tests, new exact
candidate identities and real validation.

Raw public response retained in the private job as
`openrouter-public-model-catalog.json`, SHA-256
`5319e9b091a91d36a71654553d669ee5285521edd94b0a244e3e4458d023f716`.
This does not establish authenticated routing/ZDR, remaining credit, a provider
generation, or a successful protocol probe. Pricing observations can expire;
the worker still needs an effective provider-side price fence before spending.

Google's public Interactions OpenAPI was also fetched without credentials at
`2026-09-06T14:05:49.868349Z`: API version `v1`, revision `0`, with the expected
Interactions operation path. Its canonical JSON is retained as
`google-public-interactions-openapi.json`, SHA-256
`9fac0a4a618960a2740a1d38907b2f6bd294cdd53d851eb0bb14a578f3ca5a56`.
This is only the public schema half of preflight, not the authenticated exact
model observation required by the Google probe.

## Independent review and shared-worktree boundary

The separate `p6_independent_review` chat confirmed loss of authoritative
workspace context along profile/session/queue/dispatch, incomplete operational
evidence retention/publication and the distinct native Gemini gate. A lab loop
cannot stand in for the complete release canary. Budget-delta review remains
separate from this implementer's tests and is not represented as approval here.

During this checkpoint, additional runtime edits appeared in the shared root
outside this implementer's changes, including queue/handoff files declared in
Codex's artifact. At `13:55:26Z`, their current filesystem artifact was
`a8d11f6cd051c39ab87b3453d6579c79ac8509c5e892018c4564abaac2bc4958`,
not baseline Codex 14
`33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`.
They were neither overwritten nor included in this budget checkpoint. Their
ownership/candidate deployment must be coordinated before any native cutover;
an unchanged live Codex digest cannot currently be claimed from the shared root.
