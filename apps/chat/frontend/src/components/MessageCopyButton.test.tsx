/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CopyMessageButton, type CopyMessageHandler } from "./MessageCopyButton";

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
  vi.useRealTimers();
});

describe("CopyMessageButton", () => {
  it("shows a copied check after the copy handler succeeds", async () => {
    vi.useFakeTimers();
    const onCopyMessage = vi.fn<CopyMessageHandler>(async () => true);
    const button = await renderButton(onCopyMessage);

    expect(button.textContent).toContain("content_copy");

    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(onCopyMessage).toHaveBeenCalledWith("Agent answer");
    expect(button.getAttribute("aria-label")).toBe("Message copied");
    expect(button.getAttribute("title")).toBe("Copied");
    expect(button.textContent).toContain("done");
    expect(button.classList.contains("is-copied")).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(1600);
    });

    expect(button.getAttribute("aria-label")).toBe("Copy message");
    expect(button.getAttribute("title")).toBe("Copy");
    expect(button.textContent).toContain("content_copy");
    expect(button.classList.contains("is-copied")).toBe(false);
  });

  it("keeps the copy icon when the copy handler does not confirm success", async () => {
    const onCopyMessage = vi.fn<CopyMessageHandler>(async () => false);
    const button = await renderButton(onCopyMessage);

    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    expect(button.getAttribute("aria-label")).toBe("Copy message");
    expect(button.textContent).toContain("content_copy");
    expect(button.classList.contains("is-copied")).toBe(false);
  });
});

async function renderButton(onCopyMessage: CopyMessageHandler): Promise<HTMLButtonElement> {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);

  await act(async () => {
    root?.render(<CopyMessageButton content="Agent answer" onCopyMessage={onCopyMessage} />);
  });

  const button = container.querySelector<HTMLButtonElement>("button");
  expect(button).not.toBeNull();
  return button as HTMLButtonElement;
}
