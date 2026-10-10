/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { DeviceUseControl } from "./DeviceUseControl";

let root: Root | null = null;
afterEach(() => { act(() => root?.unmount()); root = null; document.body.innerHTML = ""; });

async function render(props: Partial<ComponentProps<typeof DeviceUseControl>> = {}) {
  const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  const onModeChange = vi.fn();
  await act(async () => {
    root?.render(<DeviceUseControl busy={false} locked={false} mode="off"
      onModeChange={onModeChange} {...props} />);
  });
  return { host, button: host.querySelector("button")!, onModeChange };
}

describe("PC use toggle", () => {
  it("has one composer toggle that enables full access", async () => {
    const { host, button, onModeChange } = await render();
    expect(host.querySelectorAll("button")).toHaveLength(1);
    expect(host.querySelector('[role="radio"]')).toBeNull();
    expect(button.classList.contains("chatapp-composer__tool-button")).toBe(true);
    expect(button.getAttribute("aria-pressed")).toBe("false");
    expect(button.getAttribute("aria-label")).toBe("Attiva PC use");
    expect(button.title).toContain("accesso completo");
    await act(async () => { button.click(); });
    expect(onModeChange).toHaveBeenCalledWith("full");
  });

  it("shows the active label and switches full access off", async () => {
    const { button, onModeChange } = await render({ locked: true, pinnedMode: "full", mode: "full" });
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(button.classList.contains("is-active")).toBe(true);
    expect(button.textContent).toContain("PC use");
    await act(async () => { button.click(); });
    expect(onModeChange).toHaveBeenCalledWith("off");
  });

  it("reconnects a disconnected Full conversation with the same toggle", async () => {
    const { button, onModeChange } = await render({ locked: true, pinnedMode: "full" });
    expect(button.disabled).toBe(false);
    await act(async () => { button.click(); });
    expect(onModeChange).toHaveBeenCalledWith("full");
  });

  it.each([null] as const)("requires a new chat instead of changing a %s binding", async (pinnedMode) => {
    const { button, onModeChange } = await render({ locked: true, pinnedMode });
    expect(button.disabled).toBe(true);
    expect(button.title).toContain("nuova chat");
    await act(async () => { button.click(); });
    expect(onModeChange).not.toHaveBeenCalled();
  });


  it("prevents a second transition while a connection is pending", async () => {
    const { button, onModeChange } = await render({ busy: true });
    expect(button.disabled).toBe(true);
    await act(async () => { button.click(); });
    expect(onModeChange).not.toHaveBeenCalled();
  });
});
