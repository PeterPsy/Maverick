/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { requestJson } from "../api/client";
import { DeviceUseAuditPanel } from "./DeviceUseAuditPanel";

vi.mock("../api/client", () => ({ requestJson: vi.fn() }));
let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount()); root = null; document.body.innerHTML = ""; vi.clearAllMocks();
});

describe("Native evidence inspection", () => {
  it("loads private evidence only on inspection, pages it and clears it when the target changes", async () => {
    const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    await act(async () => root?.render(<DeviceUseAuditPanel turnId="turn-1" callId="call-1" />));
    expect(requestJson).not.toHaveBeenCalled();
    vi.mocked(requestJson).mockResolvedValueOnce({ content: "first", has_more: true, next_offset: 5, has_image: true });
    await act(async () => host.querySelector<HTMLButtonElement>("button")?.click());
    expect(host.textContent).toContain("first");
    expect(host.querySelector("img")).toBeNull();
    vi.mocked(requestJson).mockResolvedValueOnce({ content: "second", has_more: false, next_offset: null, has_image: true });
    await act(async () => host.querySelector<HTMLButtonElement>("button")?.click());
    expect(vi.mocked(requestJson).mock.calls[1][0]).toContain("offset=5");
    expect(host.textContent).toContain("firstsecond");
    await act(async () => root?.render(<DeviceUseAuditPanel turnId="turn-2" callId="call-2" />));
    expect(host.textContent).not.toContain("firstsecond");
    expect(requestJson).toHaveBeenCalledTimes(2);
  });

  it("shows unavailable historical evidence without fabricating a result", async () => {
    const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    vi.mocked(requestJson).mockRejectedValueOnce(new Error("404"));
    await act(async () => root?.render(<DeviceUseAuditPanel turnId="turn-1" callId="old-call" />));
    await act(async () => host.querySelector<HTMLButtonElement>("button")?.click());
    expect(host.querySelector('[role="status"]')?.textContent).toContain("Evidenze non disponibili");
    expect(host.querySelector("pre")).toBeNull();
  });
});
