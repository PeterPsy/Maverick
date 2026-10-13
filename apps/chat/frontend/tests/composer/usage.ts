import type { ChatUsageSummary } from "../../src/api/client";

const tokens = {
  input_tokens: 1_000_000,
  cached_input_tokens: 2_750_000,
  cache_write_input_tokens: 0,
  output_tokens: 400_000,
  reasoning_output_tokens: 100_000,
  total_tokens: 4_250_000,
};

export const fixtureUsage: ChatUsageSummary = {
  workspace_id: "default",
  root_session_id: "fixture",
  tokens,
  direct_tokens: tokens,
  delegated_tokens: { input_tokens: 0, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 0, reasoning_output_tokens: 0, total_tokens: 0 },
  context_tokens: 90_000,
  context_window_tokens: 200_000,
  context_used_percent: 45,
  context_accuracy: "exact",
  token_accuracy: "exact",
  provider_ids: ["codex"],
  model_ids: ["GPT model with a long identifier for layout validation"],
  estimated_cost_microusd: 3_450_000,
  sample_count: 3,
  coverage_since: "2026-10-13T10:05:00Z",
  updated_at: "2026-10-13T12:10:00Z",
};
