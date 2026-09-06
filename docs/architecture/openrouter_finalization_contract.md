# OpenRouter tools-omitted finalization candidate

This is a candidate protocol change, **not a release or successful live test**.
The authenticated catalog, new exact-source certification and full P6 gates
remain required. The previous frozen evidence cannot certify these new bytes.

The public DeepInfra FP8 catalog observed on 2026-09-06 reports automatic tool
selection but no explicit `tool_choice: none` support. The former contract
correctly rejected it. This candidate replaces the method, not the observation:

- Exploration with tools sends the actual catalog and `tool_choice: auto`.
- With no offered tools, including finalization and recovery, the request omits
  **both** `tools` and `tool_choice`. It never sends `tools: []` or silently
  claims explicit-none support.
- The exact model/upstream/ZDR, automatic-tool capability, parameter and context
  checks remain. Required parameters derive from the actual translated payload.
- The runtime preflight verifies omission before dispatch. Final instructions
  remain the last request-scoped system message after mandatory tool pairing.
- Unexpected proposals and their exact pending private state remain available
  for core `budget_denied` pairing and one protected recovery, then quarantine.
  Protocol generation completion is not user-turn completion: the live probe
  rejects a tool-bearing final response, and the core finalization guards must
  deny execution and reject it as a successful user final. Dropping that state
  in the codec would wrongly eliminate the required paired-recovery path.
- The receipt records `finalization_mode=omit_tools_and_choice` independently
  of the real catalog's explicit-none boolean; target/source/TCB must change.

OpenRouter documents [tool selection](https://openrouter.ai/docs/guides/features/tool-calling)
and [routing based on supplied tool parameters](https://openrouter.ai/docs/guides/routing/provider-selection).
Those references motivate the no-offered-tools method; they do not prove that
this exact endpoint follows it after retained tool history. Protocol and natural
tests must demonstrate that behavior on the pinned route before certification.
If the model continues proposing tools or cannot finalize, the candidate fails.

This work is isolated from the active installation and changes no native Codex
artifact. It neither supplies a laboratory permit nor solves the separate
session-to-dispatch authority, publisher trust, live budget or canary gates.

Focused development verification: 55 codec/catalog/recipe/finalization/budget
tests passed, including protected paired recovery. The 12 pipeline tests pass
with an explicit regression rejecting legacy receipts, another finalization
mode and a non-boolean catalog claim. A final 14 codec/catalog test pass follows
the translator cleanup. These sets overlap and are not a complete P6 suite.
No live provider request was made. The native artifact in this checkout remains
Codex 14 `33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`.

The combined isolated candidate integrates admission/publication checkpoint
`23e36403` without deploying it to the active root. It uses OpenRouter codec 3,
hosted adapter 41, Google/OpenRouter recipes 24/25, profiles 50/49 and
suite 45 / TCB 35. These identities do not certify themselves: the complete exact-source
corpus, live and natural evidence, independent review and canary remain required.
