/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RuntimeStepMessage } from "./RuntimeStepMessage";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function renderStep({
  liveInterAgentRunIds = new Set(),
  onOpenInterAgentGraph = vi.fn<(runId: string) => void>(),
  openedInterAgentGraphRunIds = new Set(),
  summaryKind,
}: {
  liveInterAgentRunIds?: ReadonlySet<string>;
  onOpenInterAgentGraph?: (runId: string) => void;
  openedInterAgentGraphRunIds?: ReadonlySet<string>;
  summaryKind: string;
}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => {
    root?.render(
      <RuntimeStepMessage
        liveInterAgentRunIds={liveInterAgentRunIds}
        onOpenInterAgentGraph={onOpenInterAgentGraph}
        openedInterAgentGraphRunIds={openedInterAgentGraphRunIds}
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
    const { element } = renderStep({ summaryKind: "plan" });

    expect(element.querySelector(".chatapp-agent-step--thought")?.textContent).toContain("Multi-agent update");
    expect(element.querySelector(".chatapp-inter-agent-message")).toBeNull();
    expect(element.querySelector(".chatapp-inter-agent-message__graph")).toBeNull();
    expect(element.querySelector(".chatapp-agent-step__board")).toBeNull();
  });

  it("shows a live board opener on active non-final inter-agent summaries", () => {
    const { element } = renderStep({ liveInterAgentRunIds: new Set(["run-1"]), summaryKind: "plan" });
    const button = element.querySelector<HTMLButtonElement>(".chatapp-agent-step__board");

    expect(button?.classList.contains("is-live")).toBe(true);
    expect(button?.classList.contains("is-pending")).toBe(false);
    expect(element.querySelector(".chatapp-live-board-glow")).not.toBeNull();
  });

  it("opens the multi-agent board from final inter-agent summaries", async () => {
    const { element, onOpenInterAgentGraph } = renderStep({ summaryKind: "completed" });
    const button = element.querySelector<HTMLButtonElement>(".chatapp-agent-step__board");

    expect(button?.textContent).toContain("Open multi-agent board");
    expect(button?.classList.contains("is-pending")).toBe(true);
    expect(element.querySelector(".chatapp-live-board-glow")).toBeNull();

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onOpenInterAgentGraph).toHaveBeenCalledWith("run-1");
  });

  it("renders final inter-agent summaries as normal after the board has been opened", () => {
    const { element } = renderStep({ openedInterAgentGraphRunIds: new Set(["run-1"]), summaryKind: "completed" });
    const button = element.querySelector<HTMLButtonElement>(".chatapp-agent-step__board");

    expect(button?.classList.contains("is-pending")).toBe(false);
    expect(button?.getAttribute("aria-label")).toBe("Open multi-agent board");
  });
});
