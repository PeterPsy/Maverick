import { afterEach, describe, expect, it, vi } from "vitest";
import { synthesizeSpeechStream } from "./speech";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("synthesizeSpeechStream", () => {
  it("opts into governed PCM streaming without exposing provider credentials", async () => {
    const response = new Response(new Uint8Array([0, 1]), {
      status: 200,
      headers: { "Content-Type": "audio/pcm", "X-Generation-Id": "gen_test" },
    });
    const fetchMock = vi.fn(async () => response);
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const result = await synthesizeSpeechStream("speech", "Ciao", {
      language: "it",
      signal: controller.signal,
    });

    expect(result).toBe(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/api/apps/speech/backend");
    expect(init.credentials).toBe("same-origin");
    expect(init.signal).toBe(controller.signal);
    expect(init.headers).toEqual(expect.objectContaining({ Accept: "audio/pcm", "Content-Type": "application/json" }));
    expect(JSON.parse(String(init.body))).toEqual({
      action: "synthesize",
      format: "pcm",
      language: "it",
      response_mode: "stream",
      text: "Ciao",
    });
    expect(String(init.body)).not.toContain("token");
  });

  it("returns provider error detail when the stream request fails before audio", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "Kokoro unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(synthesizeSpeechStream("speech", "Hello")).rejects.toMatchObject({
      name: "ApiError",
      message: "Kokoro unavailable",
      status: 503,
    });
  });
});
