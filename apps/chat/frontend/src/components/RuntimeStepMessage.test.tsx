/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RuntimeStepMessage } from "./RuntimeStepMessage";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function renderStep(summaryKind: string, onOpenInterAgentGraph = vi.fn()) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <RuntimeStepMessage
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
  return { element: container, onOpenInterAgentGraph };
}

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("RuntimeStepMessage", () => {
  it("renders runtime steps without board controls", () => {
    const { element } = renderStep("plan");

    expect(element.querySelector(".chatapp-agent-step--thought")?.textContent).toContain("Multi-agent update");
    expect(element.querySelector(".chatapp-agent-step__board")).toBeNull();
  });

  it("does not attach board controls to final inter-agent summaries", async () => {
    const { element, onOpenInterAgentGraph } = renderStep("completed");

    expect(element.querySelector(".chatapp-agent-step--thought")?.textContent).toContain("Multi-agent update");
    expect(element.querySelector(".chatapp-agent-step__board")).toBeNull();
    expect(onOpenInterAgentGraph).not.toHaveBeenCalled();
  });
});
