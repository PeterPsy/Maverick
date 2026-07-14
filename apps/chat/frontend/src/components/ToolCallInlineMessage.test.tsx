/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ToolCallInlineMessage } from "./ToolCallInlineMessage";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("ToolCallInlineMessage", () => {
  it("retains the expandable tool interaction through the shared activity disclosure", () => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() => {
      root?.render(
        <ToolCallInlineMessage
          createdAt="2026-07-14T19:46:43.000Z"
          defaultExpanded={false}
          toolCalls={[
            {
              id: "tool-1",
              name: "shell_command",
              status: "completed",
              detail: { command: "rg --files apps/chat" },
            },
          ]}
        />,
      );
    });

    const disclosure = container.querySelector<HTMLButtonElement>(".chatapp-tool-inline__toggle");
    expect(disclosure?.textContent).toContain("Tool Used");
    expect(disclosure?.getAttribute("aria-expanded")).toBe("false");

    act(() => {
      disclosure?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(disclosure?.getAttribute("aria-expanded")).toBe("true");

    const toolRow = container.querySelector<HTMLButtonElement>(".chatapp-tool-inline__row");
    expect(toolRow?.textContent).toContain("File search");
    act(() => {
      toolRow?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".chatapp-tool-call-panel")?.textContent).toContain("rg --files apps/chat");
  });
});
