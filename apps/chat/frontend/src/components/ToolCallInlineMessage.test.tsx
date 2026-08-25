/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { decideRuntimeToolConfirmation, getRuntimeToolConfirmation } from "../api/client";
import { ToolCallInlineMessage } from "./ToolCallInlineMessage";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  decideRuntimeToolConfirmation: vi.fn(),
  getRuntimeToolConfirmation: vi.fn(),
}));

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.clearAllMocks();
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
    expect(disclosure?.textContent).toContain("Actions");
    expect(disclosure?.getAttribute("aria-expanded")).toBe("false");

    act(() => {
      disclosure?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(disclosure?.getAttribute("aria-expanded")).toBe("true");

    const toolRow = container.querySelector<HTMLButtonElement>(".chatapp-tool-inline__row");
    expect(toolRow?.textContent).toContain("Listed files in apps/chat");
    act(() => {
      toolRow?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector(".chatapp-tool-call-panel")?.textContent).toContain("rg --files apps/chat");
  });

  it("binds one-shot approval to the exact invocation digest and revision", async () => {
    const confirmation = {
      turn_id: "turn-1",
      turn_status: "waiting_for_tool_confirmation",
      confirmation_deadline_at: "2026-08-16T00:01:00.000Z",
      invocation: {
        invocation_id: "invocation-1",
        tool_handle: "mcp:storage_write",
        effect_class: "mutating",
        arguments_summary: { path: "storage/generated/report.md" },
        arguments_digest: "a".repeat(64),
        state: "awaiting_confirmation",
        revision: 4,
        policy_revision: "policy:7",
      },
      confirmation: null,
    };
    vi.mocked(getRuntimeToolConfirmation).mockResolvedValue(confirmation);
    vi.mocked(decideRuntimeToolConfirmation).mockResolvedValue({
      ...confirmation,
      turn_status: "active",
      confirmation: {
        state: "active",
        expires_at: "2026-08-16T00:01:00.000Z",
        revision: 0,
      },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <ToolCallInlineMessage
          defaultExpanded
          toolCalls={[{
            id: "event-1",
            name: "mcp:storage_write",
            status: "awaiting_confirmation",
            detail: {
              turn_id: "turn-1",
              invocation_id: "invocation-1",
              arguments_digest: "a".repeat(64),
              invocation_revision: 4,
            },
          }]}
        />,
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Canonical argument summary");
    expect(container.textContent).toContain("Current invocation only");
    const approve = [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
      button.textContent?.includes("Approve once"),
    );
    await act(async () => {
      approve?.click();
      await Promise.resolve();
    });

    expect(decideRuntimeToolConfirmation).toHaveBeenCalledWith(
      "turn-1",
      "invocation-1",
      {
        decision: "approve",
        arguments_digest: "a".repeat(64),
        expected_invocation_revision: 4,
      },
    );
    expect(container.textContent).toContain("Decision recorded · active");
  });
});
