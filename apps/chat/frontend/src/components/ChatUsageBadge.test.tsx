/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ChatUsageSummary } from "../api/client";
import { ChatUsageBadge } from "./ChatUsageBadge";

const usage: ChatUsageSummary = {
  workspace_id: "default",
  root_session_id: "runtime-1",
  tokens: {
    input_tokens: 1_000_000,
    cached_input_tokens: 2_750_000,
    cache_write_input_tokens: 0,
    output_tokens: 400_000,
    reasoning_output_tokens: 100_000,
    total_tokens: 4_250_000,
  },
  direct_tokens: {
    input_tokens: 800_000,
    cached_input_tokens: 1_800_000,
    cache_write_input_tokens: 0,
    output_tokens: 300_000,
    reasoning_output_tokens: 100_000,
    total_tokens: 3_000_000,
  },
  delegated_tokens: {
    input_tokens: 200_000,
    cached_input_tokens: 950_000,
    cache_write_input_tokens: 0,
    output_tokens: 100_000,
    reasoning_output_tokens: 0,
    total_tokens: 1_250_000,
  },
  context_tokens: 90,
  context_window_tokens: 200,
  context_used_percent: 45,
  token_accuracy: "exact",
  context_accuracy: "exact",
  provider_ids: ["codex", "openrouter"],
  model_ids: ["gpt-test"],
  estimated_cost_microusd: 1250,
  sample_count: 3,
  coverage_since: "2026-08-20T10:05:00Z",
  updated_at: "2026-08-20T12:10:00Z",
};

describe("ChatUsageBadge", () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("shows numeric context and cumulative usage, then opens complete chat stats", () => {
    act(() => root.render(<ChatUsageBadge usage={usage} />));

    const badge = container.querySelector<HTMLButtonElement>(".chatapp-usage-badge");
    expect(badge?.textContent).toContain("45%");
    expect(badge?.textContent).not.toContain("context");
    expect(badge?.textContent).toContain("4.25 Mt");

    act(() => badge?.click());

    const dialog = document.body.querySelector<HTMLElement>("[role='dialog']");
    expect(dialog?.textContent).toContain("Token usage");
    expect(dialog?.textContent).toContain("Metered total");
    expect(dialog?.textContent).toContain("Root runtime");
    expect(dialog?.textContent).toContain("Delegated");
    expect(dialog?.textContent).toContain("Cached input");
    expect(dialog?.textContent).toContain("codex, openrouter");
    expect(dialog?.querySelector("[role='progressbar']")?.getAttribute("aria-valuenow")).toBe("45");
  });

  it("does not repeat the root total when the chat has no delegated usage", () => {
    const noDelegatedUsage = {
      ...usage,
      direct_tokens: usage.tokens,
      delegated_tokens: {
        input_tokens: 0,
        cached_input_tokens: 0,
        cache_write_input_tokens: 0,
        output_tokens: 0,
        reasoning_output_tokens: 0,
        total_tokens: 0,
      },
    };
    act(() => root.render(<ChatUsageBadge usage={noDelegatedUsage} />));
    act(() => container.querySelector<HTMLButtonElement>(".chatapp-usage-badge")?.click());

    const dialogText = document.body.querySelector<HTMLElement>("[role='dialog']")?.textContent || "";
    expect(dialogText).toContain("Metered total");
    expect(dialogText).not.toContain("Root runtime");
    expect(dialogText).not.toContain("Delegated");
  });

  it("closes the modal with Escape", () => {
    act(() => root.render(<ChatUsageBadge usage={usage} />));
    act(() => container.querySelector<HTMLButtonElement>(".chatapp-usage-badge")?.click());
    expect(document.body.querySelector("[role='dialog']")).not.toBeNull();

    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));

    expect(document.body.querySelector("[role='dialog']")).toBeNull();
  });
});
