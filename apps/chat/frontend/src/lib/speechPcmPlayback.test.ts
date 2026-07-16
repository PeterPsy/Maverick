import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Pcm16StreamDecoder,
  parseSpeechServerTiming,
  prepareSpeechPlaybackSession,
} from "./speechPcmPlayback";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Pcm16StreamDecoder", () => {
  it("preserves samples split across odd network chunk boundaries", () => {
    const decoder = new Pcm16StreamDecoder(24000, 24000);
    const first = decoder.decode(new Uint8Array([0x00, 0x00, 0xff]));
    const second = decoder.decode(new Uint8Array([0x7f, 0x00, 0x80]));
    const last = decoder.finish();
    const samples = [...first, ...second, ...last];

    expect(samples).toHaveLength(3);
    expect(samples[0]).toBeCloseTo(0, 6);
    expect(samples[1]).toBeCloseTo(32767 / 32768, 6);
    expect(samples[2]).toBeCloseTo(-1, 6);
  });

  it("resamples incrementally without duplicating the boundary sample", () => {
    const decoder = new Pcm16StreamDecoder(24000, 48000);
    const source = new Uint8Array([0x00, 0x00, 0xff, 0x7f, 0x00, 0x00]);
    const first = decoder.decode(source.slice(0, 4));
    const second = decoder.decode(source.slice(4));
    const samples = [...first, ...second, ...decoder.finish()];

    expect(samples.length).toBeGreaterThanOrEqual(5);
    expect(samples[0]).toBeCloseTo(0, 6);
    expect(Math.max(...samples)).toBeCloseTo(32767 / 32768, 4);
    expect(samples.at(-1)).toBeCloseTo(0, 6);
  });
});

describe("parseSpeechServerTiming", () => {
  it("returns only finite allowlisted phase timings", () => {
    expect(
      parseSpeechServerTiming(
        'backend_entrypoint;dur=84.5, upstream_connect;dur=0, upstream_headers;dur=92.25, ignored;dur=100, upstream_first_audio_byte;dur="bad"',
      ),
    ).toEqual({
      backend_entrypoint_ms: 84.5,
      upstream_connect_ms: 0,
      upstream_headers_ms: 92.25,
    });
  });
});

describe("prepareSpeechPlaybackSession", () => {
  it("promotes iPhone Web Audio to the playback session", () => {
    const audioSession = { type: "ambient" };
    vi.stubGlobal("navigator", {
      audioSession,
      maxTouchPoints: 5,
      platform: "iPhone",
      userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X)",
    });

    expect(prepareSpeechPlaybackSession()).toEqual({
      audioSessionType: "playback",
      streamingAllowed: true,
    });
    expect(audioSession.type).toBe("playback");
  });

  it("requires the media-element fallback on iOS without Audio Session support", () => {
    vi.stubGlobal("navigator", {
      maxTouchPoints: 5,
      platform: "iPhone",
      userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7 like Mac OS X)",
    });

    expect(prepareSpeechPlaybackSession()).toEqual({
      audioSessionType: "unavailable",
      streamingAllowed: false,
    });
  });

  it("keeps Web Audio available on non-Apple browsers without Audio Session support", () => {
    vi.stubGlobal("navigator", {
      maxTouchPoints: 0,
      platform: "Linux x86_64",
      userAgent: "Mozilla/5.0 (X11; Linux x86_64)",
    });

    expect(prepareSpeechPlaybackSession()).toEqual({
      audioSessionType: "unavailable",
      streamingAllowed: true,
    });
  });
});
