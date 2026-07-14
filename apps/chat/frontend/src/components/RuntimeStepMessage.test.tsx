/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import type { RuntimeStepMessage as RuntimeStep } from "../api/client";
import { isExpandableRuntimeStep, RuntimeStepMessage } from "./RuntimeStepMessage";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function renderStep(step: RuntimeStep, createdAt = "2026-07-14T19:39:04.000Z") {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => {
    root?.render(<RuntimeStepMessage createdAt={createdAt} step={step} />);
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
  it("keeps ordinary runtime progress in the compact non-interactive presentation", () => {
    const step = {
      label: "Multi-agent update",
      detail: {
        step_kind: "inter_agent_summary",
        inter_agent_run_id: "run-1",
        summary_kind: "plan",
      },
    };
    const element = renderStep(step);

    expect(isExpandableRuntimeStep(step)).toBe(false);
    expect(element.querySelector(".chatapp-agent-step--thought")?.textContent).toContain("Multi-agent update");
    expect(element.querySelector(".chatapp-agent-step__board")).toBeNull();
    expect(element.querySelector(".chatapp-tool-inline__toggle")).toBeNull();
  });

  it("renders a cleared thread goal as a collapsed activity disclosure", () => {
    const step = {
      label: "thread goal cleared",
      detail: {
        label: "thread goal cleared",
        provider_event_type: "thread.goal.cleared",
        raw: {
          type: "thread.goal.cleared",
          item: { threadId: "thread-1" },
        },
      },
    };
    const element = renderStep(step);
    const toggle = element.querySelector<HTMLButtonElement>(".chatapp-tool-inline__toggle");
    const body = element.querySelector<HTMLElement>(".chatapp-tool-inline__body");

    expect(isExpandableRuntimeStep(step)).toBe(true);
    expect(toggle?.textContent).toContain("Goal status · No active goal");
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(body?.getAttribute("aria-hidden")).toBe("true");
    expect(element.querySelector("time")?.getAttribute("dateTime")).toBe("2026-07-14T19:39:04.000Z");

    act(() => {
      toggle?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    expect(body?.getAttribute("aria-hidden")).toBe("false");
    expect(element.querySelector("[role='region']")?.textContent).toContain(
      "No active goal is currently associated with this provider thread.",
    );
    expect(element.querySelector("[role='region']")?.textContent).toContain("thread.goal.cleared");
    expect(element.querySelector("details")?.textContent).toContain("Technical details");
  });

  it("shows goal objective, status, and usage when the provider supplies them", () => {
    const element = renderStep({
      label: "thread goal updated",
      detail: {
        provider_event_type: "thread.goal.updated",
        raw: {
          type: "thread.goal.updated",
          item: {
            threadId: "thread-1",
            goal: {
              objective: "Ship the runtime disclosure",
              status: "in_progress",
              timeUsedSeconds: 75,
              tokenBudget: 12000,
              tokensUsed: 4250,
            },
          },
        },
      },
    });

    expect(element.querySelector(".chatapp-tool-inline__toggle")?.textContent).toContain("Goal status · In progress");
    expect(element.querySelector("[role='region']")?.textContent).toContain("Ship the runtime disclosure");
    expect(element.querySelector("[role='region']")?.textContent).toContain("4,250 of 12,000");
    expect(element.querySelector("[role='region']")?.textContent).toContain("1m 15s");
  });

  it("uses the same disclosure for other structured provider events", () => {
    const element = renderStep({
      label: "Provider checkpoint saved",
      detail: {
        provider_event_type: "thread.checkpoint.saved",
        raw: { type: "thread.checkpoint.saved", item: { threadId: "thread-1" } },
      },
    });

    expect(element.querySelector(".chatapp-tool-inline__toggle")?.textContent).toContain("Provider checkpoint saved");
    expect(element.querySelector("[role='region']")?.textContent).toContain("Runtime event");
    expect(element.querySelector("[role='region']")?.textContent).toContain("thread.checkpoint.saved");
  });
});
