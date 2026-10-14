// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GoogleAuthError, runGoogleFlow } from "./googleAuth";

describe("Google browser transport", () => {
  const flowId = "a".repeat(64);
  const browserUrl = "https://loopino.example/?google_handoff=1#" + "s".repeat(43) + "." + "h".repeat(64);
  const postMessage = vi.fn();
  const post = vi.fn();
  beforeEach(() => {
    vi.useFakeTimers(); window.location.href = "https://loopino.example/";
    vi.stubGlobal("webkit", { messageHandlers: { loopinoExternalURL: { postMessage } } });
    postMessage.mockResolvedValue(true);
    post.mockImplementation(async (path: string) => path.endsWith("/start") ? { browser_url: browserUrl, flow_id: flowId } : { status: "completed" });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.resetAllMocks(); });

  it("launches once through the native bridge and polls the original webview", async () => {
    const result = runGoogleFlow("connect", ["gmail", "calendar"], post);
    await vi.advanceTimersByTimeAsync(1200);
    expect(await result).toBe("completed");
    expect(postMessage).toHaveBeenCalledExactlyOnceWith({ url: browserUrl });
    expect(post).toHaveBeenNthCalledWith(1, "/api/auth/google/start", { mode: "connect", services: ["gmail", "calendar"], transport: "system-browser" }, expect.any(AbortSignal));
    expect(post).toHaveBeenNthCalledWith(2, "/api/auth/google/result", { flow_id: flowId }, expect.any(AbortSignal));
  });

  it("waits through pending consent and a temporary loss of connectivity", async () => {
    post.mockResolvedValueOnce({ browser_url: browserUrl, flow_id: flowId }).mockResolvedValueOnce({ status: "pending" })
      .mockRejectedValueOnce(new Error("network offline")).mockResolvedValueOnce({ status: "completed" });
    const result = runGoogleFlow("login", [], post);
    await vi.advanceTimersByTimeAsync(3600);
    expect(await result).toBe("completed");
  });

  it("propagates cancelled Google consent for an actionable UI error", async () => {
    post.mockResolvedValueOnce({ browser_url: browserUrl, flow_id: flowId }).mockResolvedValueOnce({ status: "failed", error: "google_consent_cancelled" });
    const result = runGoogleFlow("connect", [], post);
    const rejected = expect(result).rejects.toMatchObject({ code: "google_consent_cancelled" });
    await vi.advanceTimersByTimeAsync(1200); await rejected;
    expect(post.mock.calls.some(([path]) => path.endsWith("/cancel"))).toBe(false);
  });

  it("cancels server authority when the panel closes", async () => {
    const controller = new AbortController();
    const result = runGoogleFlow("connect", [], post, controller.signal);
    const rejected = expect(result).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(1); controller.abort(); await rejected;
    expect(post).toHaveBeenLastCalledWith("/api/auth/google/cancel", { flow_id: flowId });
  });

  it("cancels pending consent before a native server transition", async () => {
    const result = runGoogleFlow("connect", [], post);
    const rejected = expect(result).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(1);
    window.dispatchEvent(new Event("loopino.server-will-change"));
    await rejected;
    expect(post).toHaveBeenLastCalledWith("/api/auth/google/cancel", { flow_id: flowId });
    await vi.advanceTimersByTimeAsync(5000);
    expect(post.mock.calls.some(([path]) => path.endsWith("/result"))).toBe(false);
  });

  it("refuses a launch on another origin before calling the native bridge", async () => {
    post.mockResolvedValueOnce({ browser_url: browserUrl.replace("loopino.example", "evil.example"), flow_id: flowId });
    await expect(runGoogleFlow("connect", [], post)).rejects.toBeInstanceOf(GoogleAuthError);
    expect(postMessage).not.toHaveBeenCalled();
  });

  it("keeps ordinary browsers on Google's web OAuth flow", async () => {
    vi.stubGlobal("webkit", undefined);
    post.mockResolvedValueOnce({ authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=state" });
    const assign = vi.spyOn(window.location, "assign").mockImplementation(() => {});
    expect(await runGoogleFlow("login", [], post)).toBe("redirecting");
    expect(assign).toHaveBeenCalledExactlyOnceWith("https://accounts.google.com/o/oauth2/v2/auth?state=state");
    expect(postMessage).not.toHaveBeenCalled();
  });

  it("reports older iOS clients clearly without starting an unusable flow", async () => {
    vi.stubGlobal("webkit", { messageHandlers: { sensesHost: {} } });
    await expect(runGoogleFlow("login", [], post)).rejects.toMatchObject({ code: "google_native_update_required" });
    expect(post).not.toHaveBeenCalled();
  });

  it("reports older Mac clients clearly without losing the flow cookie", async () => {
    vi.stubGlobal("webkit", { messageHandlers: { loopinoDeviceUse: {} } });
    await expect(runGoogleFlow("connect", [], post)).rejects.toMatchObject({ code: "google_native_update_required" });
    expect(post).not.toHaveBeenCalled();
  });

  it("expires a browser that never completes consent and cancels server authority", async () => {
    post.mockResolvedValueOnce({ browser_url: browserUrl, flow_id: flowId }).mockResolvedValue({ status: "pending" });
    const result = runGoogleFlow("connect", [], post);
    const rejected = expect(result).rejects.toMatchObject({ code: "google_flow_expired" });
    await vi.advanceTimersByTimeAsync(600_000); await rejected;
    expect(post).toHaveBeenLastCalledWith("/api/auth/google/cancel", { flow_id: flowId });
  });
});
