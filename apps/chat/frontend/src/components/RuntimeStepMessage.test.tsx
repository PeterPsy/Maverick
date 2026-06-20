/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RuntimeStepMessage } from "./RuntimeStepMessage";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function renderStep(summaryKind: string, interAgentRunStatusById: Record<string, string> = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <RuntimeStepMessage
        interAgentRunStatusById={interAgentRunStatusById}
        onOpenInterAgentGraph={vi.fn()}
        step={{
          label: "Multi-agent update",
          detail: {
            step_kind: "inter_agent_summary",
            inter_agent_run_id: "run-1",
            summary_kind: summaryKind,
          },
        }}
      />,
    );
  });
  return container;
}

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("RuntimeStepMessage", () => {
  it("pulses Agent nodes only for non-terminal inter-agent steps", () => {
    let element = renderStep("plan");
    expect(element.querySelector(".chatapp-inter-agent-message__graph")?.classList.contains("is-live")).toBe(true);

    root?.unmount();
    container?.remove();

    element = renderStep("completed");
    expect(element.querySelector(".chatapp-inter-agent-message__graph")?.classList.contains("is-live")).toBe(false);
  });

  it("uses the current run status when an older step payload is still non-terminal", () => {
    const element = renderStep("plan", { "run-1": "completed" });

    expect(element.querySelector(".chatapp-inter-agent-message__graph")?.classList.contains("is-live")).toBe(false);
  });
});
