/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StructuredContentMessage } from "./StructuredContentMessage";

const apiMocks = vi.hoisted(() => ({
  createWidgetContext: vi.fn(),
  listWidgets: vi.fn(),
}));

vi.mock("../api/client", () => apiMocks);

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.clearAllMocks();
});

describe("StructuredContentMessage", () => {
  it("uses the canonical Maverick spinner while widget discovery is pending", async () => {
    apiMocks.listWidgets.mockReturnValue(new Promise(() => undefined));
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <StructuredContentMessage
          content={{ kind: "checklist.design", payload: { id: "check_123" } }}
          messageId="message-1"
        />,
      );
    });

    const loader = container.querySelector('[role="status"][aria-label="Loading widget"]');
    expect(loader?.querySelector(".chatapp-morphing-spinner")).toBeInstanceOf(HTMLSpanElement);
    expect(container.querySelector(".chatapp-structured-card")).toBeNull();
    expect(container.textContent).not.toContain("check_123");
    expect(container.textContent).not.toContain("Ricerca widget compatibile");
  });
});
