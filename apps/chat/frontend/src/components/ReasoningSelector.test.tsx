/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReasoningSelector } from "./ReasoningSelector";

let container: HTMLDivElement | null = null;

afterEach(() => {
  container?.remove();
  container = null;
});

function renderSelector(options: Parameters<typeof ReasoningSelector>[0]) {
  container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(<ReasoningSelector {...options} />));
  return container;
}

describe("ReasoningSelector", () => {
  it("renders only supported efforts and reports the per-chat selection", () => {
    const onChange = vi.fn();
    const element = renderSelector({
      disabled: false,
      onChange,
      options: [
        { effort: "high", label: "High", description: null },
        { effort: "xhigh", label: "Extra high", description: null },
      ],
      value: "xhigh",
    });
    const select = element.querySelector("select") as HTMLSelectElement;
    expect(select.value).toBe("xhigh");
    act(() => {
      select.value = "high";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith("high");
  });

  it("stays hidden when the model exposes no reasoning control", () => {
    const element = renderSelector({ disabled: false, onChange: () => undefined, options: [], value: "" });
    expect(element.innerHTML).toBe("");
  });
});
