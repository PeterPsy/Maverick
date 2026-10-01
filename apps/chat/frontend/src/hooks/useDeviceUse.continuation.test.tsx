/** @vitest-environment happy-dom */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createDeviceUseActivation, getDeviceUseActivation, reconnectDeviceUseSession, stopDeviceUseActivation,
  type ChatThread, type DeviceUseActivation, type ProviderItem,
} from "../api/client";
import { requestNativeDeviceUse, type NativeDeviceUseSnapshot } from "../lib/deviceUse";
import { useDeviceUse } from "./useDeviceUse";

vi.mock("../api/client", () => ({
  createDeviceUseActivation: vi.fn(), getDeviceUseActivation: vi.fn(),
  reconnectDeviceUseSession: vi.fn(), stopDeviceUseActivation: vi.fn(),
}));
vi.mock("../lib/deviceUse", () => ({ requestNativeDeviceUse: vi.fn() }));

const oldId = "00000000-0000-0000-0000-000000000001";
const newId = "00000000-0000-0000-0000-000000000002";
const activation = (id: string): DeviceUseActivation => ({
  activation_id: id, ready: true, bound: true, status: "bound", mode: "full",
});
const originalThread = {
  thread_id: "thread", runtime_session_id: "session", device_use_enabled: true,
  device_use: activation(oldId),
} as ChatThread;
const provider = {
  provider_id: "codex", runtime_engine_id: "codex", provider_role: "runtime_engine",
  workspace_profile_binding_id: "profile", status: "active",
} as ProviderItem;
const onPrepare = vi.fn();
const onReconnected = vi.fn();
let result: ReturnType<typeof useDeviceUse>;
let root: Root | null = null;
let native: NativeDeviceUseSnapshot;
let currentThread: ChatThread | null;

function Harness({ thread }: { thread: ChatThread | null }) {
  result = useDeviceUse({ activeThread: thread, provider, reasoningEffort: "max", onPrepare,
    onReconnected: (previous, ready) => {
      onReconnected(previous, ready);
      currentThread = { ...previous, device_use: ready };
      root?.render(<Harness thread={currentThread} />);
    },
  });
  return null;
}

async function render(thread: ChatThread | null = originalThread) {
  currentThread = thread;
  if (!root) {
    const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  }
  await act(async () => { root?.render(<Harness thread={thread} />); });
}

beforeEach(() => {
  vi.resetAllMocks();
  native = {
    available: true, active: true, activationId: oldId, mode: "full", phase: "ready", notice: "",
    apps: [], permissions: { screen: true, accessibility: true, input: true },
    settings: { selectedApp: "com.apple.Safari", additionalApps: [], consentMode: "perTask" },
  };
  vi.mocked(getDeviceUseActivation).mockImplementation(async (id) => activation(id));
  vi.mocked(createDeviceUseActivation).mockResolvedValue({
    ...activation(newId), bound: false, ticket: "one-shot-ticket", websocket_path: "/ws/device-use/executor",
  });
  vi.mocked(reconnectDeviceUseSession).mockResolvedValue(activation(newId));
  vi.mocked(stopDeviceUseActivation).mockResolvedValue({ status: "stopped" });
  vi.mocked(requestNativeDeviceUse).mockImplementation(async (action, options) => {
    if (action === "start") native = { ...native, active: true, activationId: options!.activationId!, mode: options!.mode!, phase: "ready" };
    if (action === "stop") native = { ...native, active: false, activationId: null, mode: "off", phase: "stopped" };
    return native;
  });
});
afterEach(() => { act(() => root?.unmount()); root = null; document.body.innerHTML = ""; });

describe("Device Use conversation continuation", () => {
  it("keeps a healthy returning conversation active without a new activation", async () => {
    await render();
    expect(result.mode).toBe("full");
    expect(result.pinnedMode).toBe("full");
    await act(async () => { await result.ensureReady(); });
    expect(createDeviceUseActivation).not.toHaveBeenCalled();
    expect(reconnectDeviceUseSession).not.toHaveBeenCalled();
  });

  it("shows Off after Core lost the activation, preserving capability restrictions", async () => {
    vi.mocked(getDeviceUseActivation).mockRejectedValue(new Error("device_use_activation_not_found"));
    await render();
    expect(result.mode).toBe("off");
    expect(result.enabled).toBe(true);
    expect(result.locked).toBe(true);
    await act(async () => { await expect(result.ensureReady()).rejects.toThrow("Premi Full"); });
    expect(createDeviceUseActivation).not.toHaveBeenCalled();
    expect(requestNativeDeviceUse).not.toHaveBeenCalledWith("start", expect.anything());
  });

  it("checks the current activation before submission even if the UI still shows Full", async () => {
    await render();
    vi.mocked(getDeviceUseActivation).mockRejectedValue(new Error("device_use_activation_not_found"));
    await act(async () => { await expect(result.ensureReady()).rejects.toThrow("Mac scollegato"); });
    expect(result.mode).toBe("off");
  });

  it("reconnects the same thread only on explicit selection of its pinned mode", async () => {
    native = { ...native, active: false, activationId: null, mode: "off" };
    await render();
    await act(async () => { await result.selectMode("full"); });
    expect(reconnectDeviceUseSession).toHaveBeenCalledWith("session", newId, oldId);
    expect(onPrepare).not.toHaveBeenCalled();
    expect(onReconnected).toHaveBeenCalledWith(originalThread, activation(newId));
    expect(result.mode).toBe("full");
    await act(async () => { await result.ensureReady(); });
    expect(result.error).toBeNull();
  });

  it("rejects mode changes and conversion of an ordinary existing conversation", async () => {
    native = { ...native, active: false, mode: "off" };
    await render();
    await act(async () => { await result.selectMode("on"); });
    expect(result.error).toContain("modalità è fissata");
    await render({ ...originalThread, device_use_enabled: false, device_use: null });
    await act(async () => { await result.selectMode("full"); });
    expect(createDeviceUseActivation).not.toHaveBeenCalled();
  });

  it("does not resurrect an explicitly stopped lease when navigating away and back", async () => {
    await render();
    await act(async () => { await result.selectMode("off"); });
    expect(stopDeviceUseActivation).toHaveBeenCalledWith(oldId);
    await render(null);
    await render();
    expect(result.mode).toBe("off");
    expect(createDeviceUseActivation).not.toHaveBeenCalled();
    await act(async () => { await expect(result.ensureReady()).rejects.toThrow("Premi Full"); });
  });

  it("refreshes native and Core status on return to the foreground", async () => {
    await render();
    native = { ...native, active: false, activationId: null, mode: "off" };
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(result.mode).toBe("off");
  });

  it("ignores an old status response after navigation to another thread", async () => {
    let resolveOld!: (activation: DeviceUseActivation) => void;
    vi.mocked(getDeviceUseActivation).mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }));
    await render();
    native = { ...native, activationId: newId };
    await render({ ...originalThread, thread_id: "other", device_use: activation(newId) });
    expect(result.mode).toBe("full");
    await act(async () => { resolveOld({ ...activation(oldId), ready: false }); });
    expect(result.mode).toBe("full");
  });

  it("revokes an unsuccessful new activation without sending any user action", async () => {
    native = { ...native, active: false, mode: "off" };
    vi.mocked(reconnectDeviceUseSession).mockRejectedValue(new Error("device_use_reconnect_scope_changed"));
    await render();
    await act(async () => { await result.selectMode("full"); });
    expect(stopDeviceUseActivation).toHaveBeenCalledWith(newId);
    expect(result.mode).toBe("off");
    expect(result.error).toContain("impostazioni On sono diverse");
    expect(onReconnected).not.toHaveBeenCalled();
  });
});
