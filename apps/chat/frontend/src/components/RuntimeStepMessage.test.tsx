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
        onOpenInterAgentGraph={onOpenInterAgentGraph}
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
  it("keeps non-final inter-agent summaries as plain runtime steps", () => {
    const { element } = renderStep("plan");

    expect(element.querySelector(".chatapp-agent-step--thought")?.textContent).toContain("Multi-agent update");
    expect(element.querySelector(".chatapp-inter-agent-message")).toBeNull();
    expect(element.querySelector(".chatapp-inter-agent-message__graph")).toBeNull();
    expect(element.querySelector(".chatapp-agent-step__board")).toBeNull();
  });

  it("opens the multi-agent board from final inter-agent summaries", async () => {
    const { element, onOpenInterAgentGraph } = renderStep("completed");
    const button = element.querySelector<HTMLButtonElement>(".chatapp-agent-step__board");

    expect(button?.textContent).toContain("Open multi-agent board");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenInterAgentGraph).toHaveBeenCalledWith("run-1");
  });
});
