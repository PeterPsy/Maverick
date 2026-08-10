/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { MarkdownMessage } from "./MarkdownMessage";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

describe("MarkdownMessage", () => {
  it("opens absolute http links in a separate browser context", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<MarkdownMessage content={"[Apple Developer](https://developer.apple.com/register/)"} />);
    });

    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://developer.apple.com/register/");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("keeps relative non-storage links inside the current frame", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(<MarkdownMessage content={"[Internal docs](/docs/getting-started)"} />);
    });

    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("/docs/getting-started");
    expect(link?.getAttribute("target")).toBeNull();
    expect(link?.getAttribute("rel")).toBeNull();
  });

  it("routes workspace storage links through the shell instead of navigating the chat frame", async () => {
    const messages: Array<{ message: unknown; targetOrigin: string }> = [];
    const originalParent = window.parent;
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: {
        postMessage(message: unknown, targetOrigin: string) {
          messages.push({ message, targetOrigin });
        },
      },
    });
    try {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);

      await act(async () => {
        root?.render(
          <MarkdownMessage
            content={
              "[agents-cli-mcp-speed-report.md](/home/ubuntu/projects/maverick-v3/workspaces/default/storage/generated/agents-cli-mcp-speed-report.md:1)"
            }
          />,
        );
      });

      const link = container.querySelector("a");
      expect(link?.getAttribute("href")).toBe(
        "/app/storage?workspace_relative_path=storage%2Fgenerated%2Fagents-cli-mcp-speed-report.md",
      );
      expect(link?.getAttribute("target")).toBeNull();

      link?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

      expect(messages[0]?.message).toEqual({
        type: "maverick.app.open-app",
        app_id: "storage",
        params: { workspace_relative_path: "storage/generated/agents-cli-mcp-speed-report.md" },
      });
    } finally {
      Object.defineProperty(window, "parent", { configurable: true, value: originalParent });
    }
  });

  it("routes Storage deep links through the shell", async () => {
    const messages: Array<{ message: unknown; targetOrigin: string }> = [];
    const originalParent = window.parent;
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: {
        postMessage(message: unknown, targetOrigin: string) {
          messages.push({ message, targetOrigin });
        },
      },
    });
    try {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);

      await act(async () => {
        root?.render(<MarkdownMessage content={"[Open in Storage](/app/storage/files/file_123)"} />);
      });

      const link = container.querySelector("a");
      expect(link?.getAttribute("href")).toBe("/app/storage/files/file_123");
      expect(link?.getAttribute("target")).toBeNull();

      link?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

      expect(messages[0]?.message).toEqual({
        type: "maverick.app.open-app",
        app_id: "storage",
        params: { app_page: "files/file_123" },
      });
    } finally {
      Object.defineProperty(window, "parent", { configurable: true, value: originalParent });
    }
  });

  it("routes Mail deep links through the shell instead of navigating the Chat frame", async () => {
    const messages: Array<{ message: unknown; targetOrigin: string }> = [];
    const originalParent = window.parent;
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: {
        postMessage(message: unknown, targetOrigin: string) {
          messages.push({ message, targetOrigin });
        },
      },
    });
    try {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);

      await act(async () => {
        root?.render(<MarkdownMessage content={"[Open in Mail](/app/mail?thread=email_thread_123)"} />);
      });

      const link = container.querySelector("a");
      expect(link?.getAttribute("href")).toBe("/app/mail?thread=email_thread_123");

      const click = new MouseEvent("click", { bubbles: true, cancelable: true });
      link?.dispatchEvent(click);

      expect(click.defaultPrevented).toBe(true);
      expect(messages[0]?.message).toEqual({
        type: "maverick.app.open-app",
        app_id: "mail",
        params: { thread: "email_thread_123" },
      });
    } finally {
      Object.defineProperty(window, "parent", { configurable: true, value: originalParent });
    }
  });
});
