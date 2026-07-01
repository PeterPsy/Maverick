/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { RuntimeStepMessage } from "./RuntimeStepMessage";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function renderStep(summaryKind: string) {
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
  return container;
}

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("RuntimeStepMessage", () => {
  it("renders inter-agent summaries as plain runtime steps", () => {
    const element = renderStep("plan");

    expect(element.querySelector(".chatapp-agent-step--thought")?.textContent).toContain("Multi-agent update");
    expect(element.querySelector(".chatapp-inter-agent-message")).toBeNull();
    expect(element.querySelector(".chatapp-inter-agent-message__graph")).toBeNull();
  });
});
