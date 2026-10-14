// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearNativeServerSession, getServerProfiles, normalizeServerOrigin, removeServerProfile, saveServerProfile, switchServerProfile } from "./serverProfiles";

beforeEach(() => { localStorage.clear(); delete (window as unknown as { webkit?: unknown }).webkit; });
afterEach(() => { delete (window as unknown as { webkit?: unknown }).webkit; });

describe("local server profiles", () => {
  it("normalizes origins and rejects credentials or callback paths", () => {
    expect(normalizeServerOrigin(" https://TRAIL.example:443/ ")).toBe("https://trail.example");
    for (const url of ["http://example.com", "https://user:password@example.com", "https://example.com/app/chat", "https://example.com/?token=secret", "https://example.com/#callback"]) {
      expect(() => normalizeServerOrigin(url)).toThrow();
    }
  });
  it("stores browser bookmarks without login material and preserves the current origin", async () => {
    const result = await saveServerProfile("GiuntiTrail", "https://trail.example");
    expect(result.native).toBe(false);
    expect(result.profiles[0].current).toBe(true);
    expect(result.profiles[1]).toEqual({ id: "https://trail.example", name: "GiuntiTrail", origin: "https://trail.example", current: false });
    await expect(removeServerProfile(result.profiles[0].id)).rejects.toThrow("Switch servers");
    const renamed = await saveServerProfile("Trail renamed", "https://trail.example", result.profiles[1].id);
    expect(renamed.profiles[1].id).toBe(result.profiles[1].id);
    expect((await removeServerProfile(result.profiles[1].id)).profiles).toHaveLength(1);
  });
  it("routes switching and logout to the native profile bridge without transmitting credentials", async () => {
    const profile = { id: "profile-b", name: "Trail", origin: "https://trail.example", current: false };
    const postMessage = vi.fn().mockResolvedValue({ profiles: [profile] });
    (window as unknown as { webkit: unknown }).webkit = { messageHandlers: { loopinoServers: { postMessage } } };
    expect((await getServerProfiles()).native).toBe(true);
    await switchServerProfile(profile);
    await clearNativeServerSession();
    expect(postMessage.mock.calls.map(call => call[0])).toEqual([{ action: "list" }, { action: "switch", id: "profile-b" }, { action: "logout" }]);
    expect(localStorage.length).toBe(0);
  });
  it("reports rejected native transitions without using a browser navigation fallback", async () => {
    const postMessage = vi.fn().mockRejectedValue(new Error("Server unavailable"));
    (window as unknown as { webkit: unknown }).webkit = { messageHandlers: { loopinoServers: { postMessage } } };
    await expect(switchServerProfile({ id: "b", name: "B", origin: "https://b.example", current: false })).rejects.toThrow("Server unavailable");
  });
  it("requires a native update on older clients instead of creating unusable browser bookmarks", async () => {
    (window as unknown as { webkit: unknown }).webkit = { messageHandlers: { sensesHost: {} } };
    await expect(getServerProfiles()).rejects.toThrow("Update the Loopino native app");
    await expect(saveServerProfile("Trail", "https://trail.example")).rejects.toThrow("Update the Loopino native app");
    expect(localStorage.length).toBe(0);
  });
});
