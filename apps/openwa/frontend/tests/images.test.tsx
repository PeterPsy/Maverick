import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MessageImage } from "../src/MessageImage";
import { operation } from "../src/api";

vi.mock("../src/api", () => ({ operation: vi.fn() }));
const request = vi.mocked(operation);
let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  request.mockReset();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
async function render() {
  await act(async () => root.render(<MessageImage sessionId="phone" chatId="123@lid" messageId="wa-image" available />));
}
async function click() { await act(async () => container.querySelector("button")!.click()); }

it("loads only the selected image on demand", async () => {
  request.mockResolvedValue({ mimetype: "image/jpeg", content_base64: "aW1hZ2U=" });
  await render();
  expect(request).not.toHaveBeenCalled();
  await click();
  expect(request).toHaveBeenCalledWith("messages.image", {
    session_id: "phone", chat_id: "123@lid", message_id: "wa-image",
  }, expect.any(AbortSignal));
  expect(container.querySelector("img")!.src).toBe("data:image/jpeg;base64,aW1hZ2U=");
});

it("shows missing-media failures and allows retry without sending", async () => {
  request.mockRejectedValueOnce(new Error("Image no longer available"));
  await render(); await click();
  expect(container.querySelector('[role="alert"]')!.textContent).toContain("no longer available");
  request.mockResolvedValue({ mimetype: "image/png", content_base64: "aW1hZ2U=" });
  await click();
  expect(container.querySelector("img")).not.toBeNull();
  expect(container.querySelector('[role="alert"]')).toBeNull();
});

it("cancels obsolete image reads on unmount", async () => {
  let finish!: (value: unknown) => void;
  request.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  await render(); await click();
  const signal = request.mock.calls[0][2]!;
  await act(async () => root.render(<div>Another conversation</div>));
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ mimetype: "image/jpeg", content_base64: "aW1hZ2U=" }));
  expect(container.querySelector("img")).toBeNull();
});
