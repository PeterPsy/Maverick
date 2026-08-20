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
    input_tokens: 150,
    cached_input_tokens: 30,
    cache_write_input_tokens: 0,
    output_tokens: 55,
    reasoning_output_tokens: 15,
    total_tokens: 250,
  },
  direct_tokens: {
    input_tokens: 130,
    cached_input_tokens: 30,
    cache_write_input_tokens: 0,
    output_tokens: 50,
    reasoning_output_tokens: 15,
    total_tokens: 225,
  },
  delegated_tokens: {
    input_tokens: 20,
    cached_input_tokens: 0,
    cache_write_input_tokens: 0,
    output_tokens: 5,
    reasoning_output_tokens: 0,
    total_tokens: 25,
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
    expect(badge?.textContent).toContain("45% context");
    expect(badge?.textContent).toContain("250 tokens");

    act(() => badge?.click());

    const dialog = document.body.querySelector<HTMLElement>("[role='dialog']");
    expect(dialog?.textContent).toContain("Token usage");
    expect(dialog?.textContent).toContain("Chat total");
    expect(dialog?.textContent).toContain("Delegated");
    expect(dialog?.textContent).toContain("Cached input");
    expect(dialog?.textContent).toContain("codex, openrouter");
    expect(dialog?.querySelector("[role='progressbar']")?.getAttribute("aria-valuenow")).toBe("45");
  });

  it("closes the modal with Escape", () => {
    act(() => root.render(<ChatUsageBadge usage={usage} />));
    act(() => container.querySelector<HTMLButtonElement>(".chatapp-usage-badge")?.click());
    expect(document.body.querySelector("[role='dialog']")).not.toBeNull();

    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));

    expect(document.body.querySelector("[role='dialog']")).toBeNull();
  });
});
