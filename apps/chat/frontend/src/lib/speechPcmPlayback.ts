const PCM_WORKLET_NAME = "maverick-pcm-stream-player";
const DEFAULT_INITIAL_BUFFER_MS = 60;

const PCM_WORKLET_SOURCE = `
class MaverickPcmStreamPlayer extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.queue = [];
    this.offset = 0;
    this.bufferedFrames = 0;
    this.started = false;
    this.ended = false;
    this.stopped = false;
    this.underrunActive = false;
    const bufferMs = Number(options.processorOptions?.initialBufferMs || 60);
    this.initialFrames = Math.max(1, Math.round(sampleRate * bufferMs / 1000));
    this.port.onmessage = (event) => {
      if (event.data?.type === "data" && event.data.samples?.length) {
        this.queue.push(event.data.samples);
        this.bufferedFrames += event.data.samples.length;
        this.underrunActive = false;
      } else if (event.data?.type === "end") {
        this.ended = true;
      } else if (event.data?.type === "stop") {
        this.stopped = true;
      }
    };
  }

  process(_inputs, outputs) {
    if (this.stopped) return false;
    const output = outputs[0]?.[0];
    if (!output) return true;
    output.fill(0);
    if (!this.started && (this.bufferedFrames >= this.initialFrames || (this.ended && this.bufferedFrames > 0))) {
      this.started = true;
      this.port.postMessage({ type: "playing" });
    }
    if (!this.started) {
      if (this.ended && this.bufferedFrames === 0) {
        this.port.postMessage({ type: "error", message: "PCM stream ended before audio arrived." });
        return false;
      }
      return true;
    }
    let outputOffset = 0;
    while (outputOffset < output.length && this.queue.length) {
      const current = this.queue[0];
      const available = current.length - this.offset;
      const length = Math.min(available, output.length - outputOffset);
      output.set(current.subarray(this.offset, this.offset + length), outputOffset);
      outputOffset += length;
      this.offset += length;
      this.bufferedFrames -= length;
      if (this.offset >= current.length) {
        this.queue.shift();
        this.offset = 0;
      }
    }
    if (outputOffset < output.length && !this.ended && !this.underrunActive) {
      this.underrunActive = true;
      this.port.postMessage({ type: "underrun" });
    }
    if (this.ended && this.bufferedFrames === 0) {
      this.port.postMessage({ type: "ended" });
      return false;
    }
    return true;
  }
}
registerProcessor("${PCM_WORKLET_NAME}", MaverickPcmStreamPlayer);
`;

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext;
type BrowserAudioSession = { type?: string };
type NavigatorWithAudioSession = Navigator & { audioSession?: BrowserAudioSession };

export type SpeechPlaybackSession = {
  audioSessionType: string;
  streamingAllowed: boolean;
};

export type SpeechPcmPlaybackMetrics = {
  audio_context_state?: string;
  audio_session_type?: string;
  backend_entrypoint_ms?: number;
  browser_first_chunk_ms?: number;
  generation_id?: string;
  mode: "pcm-stream" | "buffered";
  outcome?: "playing" | "completed" | "cancelled" | "failed";
  playback_id: string;
  failure_code?: string;
  tap_to_audio_playing_ms?: number;
  tap_to_request_ms?: number;
  underrun_count?: number;
  upstream_connect_ms?: number;
  upstream_first_audio_byte_ms?: number;
  upstream_headers_ms?: number;
};

export class Pcm16StreamDecoder {
  private readonly ratio: number;
  private pendingSamples = new Float32Array(0);
  private sourcePosition = 0;
  private carryByte: number | null = null;

  constructor(
    readonly sourceSampleRate: number,
    readonly targetSampleRate: number,
  ) {
    if (!Number.isFinite(sourceSampleRate) || sourceSampleRate <= 0 || !Number.isFinite(targetSampleRate) || targetSampleRate <= 0) {
      throw new Error("PCM sample rates must be positive numbers.");
    }
    this.ratio = sourceSampleRate / targetSampleRate;
  }

  decode(chunk: Uint8Array): Float32Array {
    let bytes = chunk;
    if (this.carryByte !== null) {
      const joined = new Uint8Array(chunk.length + 1);
      joined[0] = this.carryByte;
      joined.set(chunk, 1);
      bytes = joined;
      this.carryByte = null;
    }
    if (bytes.length % 2 === 1) {
      this.carryByte = bytes.at(-1) ?? null;
      bytes = bytes.subarray(0, bytes.length - 1);
    }
    if (!bytes.length) {
      return new Float32Array(0);
    }
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const incoming = new Float32Array(bytes.length / 2);
    for (let index = 0; index < incoming.length; index += 1) {
      incoming[index] = view.getInt16(index * 2, true) / 32768;
    }
    const combined = new Float32Array(this.pendingSamples.length + incoming.length);
    combined.set(this.pendingSamples);
    combined.set(incoming, this.pendingSamples.length);
    this.pendingSamples = combined;
    return this.drainInterpolatedSamples();
  }

  finish(): Float32Array {
    if (this.carryByte !== null) {
      throw new Error("PCM stream ended on an incomplete 16-bit sample.");
    }
    const drained = this.drainInterpolatedSamples();
    const tail = this.pendingSamples.length ? this.pendingSamples.at(-1) : undefined;
    this.pendingSamples = new Float32Array(0);
    this.sourcePosition = 0;
    if (tail === undefined) {
      return drained;
    }
    const output = new Float32Array(drained.length + 1);
    output.set(drained);
    output[drained.length] = tail;
    return output;
  }

  private drainInterpolatedSamples(): Float32Array {
    if (this.pendingSamples.length < 2) {
      return new Float32Array(0);
    }
    const output: number[] = [];
    while (this.sourcePosition < this.pendingSamples.length - 1) {
      const leftIndex = Math.floor(this.sourcePosition);
      const fraction = this.sourcePosition - leftIndex;
      const left = this.pendingSamples[leftIndex];
      const right = this.pendingSamples[leftIndex + 1];
      output.push(left + (right - left) * fraction);
      this.sourcePosition += this.ratio;
    }
    const consumed = Math.floor(this.sourcePosition);
    if (consumed > 0) {
      this.pendingSamples = this.pendingSamples.slice(consumed);
      this.sourcePosition -= consumed;
    }
    return Float32Array.from(output);
  }
}

export class PcmStreamPlayer {
  readonly audioSessionType: string;
  readonly context: AudioContext;
  readonly decoder: Pcm16StreamDecoder;
  private readonly node: AudioWorkletNode;
  private readonly completion: Promise<void>;
  private resolveCompletion: (() => void) | null = null;
  private rejectCompletion: ((error: Error) => void) | null = null;
  private stopped = false;
  private _started = false;
  private _underrunCount = 0;

  private constructor(
    context: AudioContext,
    node: AudioWorkletNode,
    sourceSampleRate: number,
    audioSessionType: string,
    onPlaying?: () => void,
  ) {
    this.audioSessionType = audioSessionType;
    this.context = context;
    this.node = node;
    this.decoder = new Pcm16StreamDecoder(sourceSampleRate, context.sampleRate);
    this.completion = new Promise<void>((resolve, reject) => {
      this.resolveCompletion = resolve;
      this.rejectCompletion = reject;
    });
    node.port.onmessage = (event: MessageEvent<{ type?: string; message?: string }>) => {
      if (event.data?.type === "playing") {
        this._started = true;
        onPlaying?.();
      } else if (event.data?.type === "underrun") {
        this._underrunCount += 1;
      } else if (event.data?.type === "ended") {
        this.resolveCompletion?.();
      } else if (event.data?.type === "error") {
        this.rejectCompletion?.(new Error(event.data.message || "PCM playback failed."));
      }
    };
  }

  static async create({
    sourceSampleRate,
    initialBufferMs = DEFAULT_INITIAL_BUFFER_MS,
    onPlaying,
  }: {
    sourceSampleRate: number;
    initialBufferMs?: number;
    onPlaying?: () => void;
  }): Promise<PcmStreamPlayer> {
    const playbackSession = prepareSpeechPlaybackSession();
    const Context = audioContextConstructor();
    if (!playbackSession.streamingAllowed || !Context || typeof AudioWorkletNode === "undefined") {
      throw new Error("Progressive PCM playback is unavailable in this browser.");
    }
    const context = new Context({ latencyHint: "interactive" });
    try {
      await context.resume();
      if (context.state !== "running") {
        throw new Error("Progressive PCM playback could not activate the browser audio context.");
      }
      const moduleUrl = URL.createObjectURL(new Blob([PCM_WORKLET_SOURCE], { type: "text/javascript" }));
      try {
        await context.audioWorklet.addModule(moduleUrl);
      } finally {
        URL.revokeObjectURL(moduleUrl);
      }
      const node = new AudioWorkletNode(context, PCM_WORKLET_NAME, {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { initialBufferMs },
      });
      node.connect(context.destination);
      return new PcmStreamPlayer(
        context,
        node,
        sourceSampleRate,
        playbackSession.audioSessionType,
        onPlaying,
      );
    } catch (error) {
      await context.close();
      throw error;
    }
  }

  get started(): boolean {
    return this._started;
  }

  get underrunCount(): number {
    return this._underrunCount;
  }

  get contextState(): string {
    return String(this.context.state || "unknown");
  }

  append(chunk: Uint8Array): void {
    if (this.stopped) {
      return;
    }
    this.postSamples(this.decoder.decode(chunk));
  }

  async finish(): Promise<void> {
    if (this.stopped) {
      return;
    }
    this.postSamples(this.decoder.finish());
    this.node.port.postMessage({ type: "end" });
    await this.completion;
  }

  stop(): void {
    if (this.stopped) {
      return;
    }
    this.stopped = true;
    this.node.port.postMessage({ type: "stop" });
    this.node.disconnect();
    this.resolveCompletion?.();
    void this.context.close();
  }

  private postSamples(samples: Float32Array): void {
    if (!samples.length) {
      return;
    }
    this.node.port.postMessage({ type: "data", samples }, [samples.buffer]);
  }
}

export function supportsPcmStreamingPlayback(): boolean {
  const playbackSession = prepareSpeechPlaybackSession();
  return Boolean(
    playbackSession.streamingAllowed
      && audioContextConstructor()
      && typeof AudioWorkletNode !== "undefined"
      && typeof ReadableStream !== "undefined",
  );
}

export function prepareSpeechPlaybackSession(): SpeechPlaybackSession {
  const navigatorObject = typeof navigator === "undefined"
    ? null
    : navigator as NavigatorWithAudioSession;
  const audioSession = navigatorObject?.audioSession;
  if (audioSession) {
    try {
      audioSession.type = "playback";
    } catch {
      // Older WebKit builds may expose a read-only or partial Audio Session API.
    }
  }
  const audioSessionType = normalizedAudioSessionType(audioSession?.type);
  return {
    audioSessionType,
    streamingAllowed: !isAppleMobileBrowser(navigatorObject) || audioSessionType === "playback",
  };
}

export function parseSpeechServerTiming(value: string): Partial<SpeechPcmPlaybackMetrics> {
  const names: Record<string, keyof SpeechPcmPlaybackMetrics> = {
    backend_entrypoint: "backend_entrypoint_ms",
    upstream_connect: "upstream_connect_ms",
    upstream_headers: "upstream_headers_ms",
    upstream_first_audio_byte: "upstream_first_audio_byte_ms",
  };
  const metrics: Partial<SpeechPcmPlaybackMetrics> = {};
  for (const entry of value.split(",")) {
    const [rawName, ...parameters] = entry.trim().split(";");
    const metricName = names[rawName];
    if (!metricName) {
      continue;
    }
    const durationParameter = parameters.find((parameter) => parameter.trim().startsWith("dur="));
    const duration = Number(durationParameter?.trim().slice(4));
    if (Number.isFinite(duration) && duration >= 0) {
      (metrics as Record<string, number>)[metricName] = duration;
    }
  }
  return metrics;
}

export function publishSpeechPlaybackMetrics(metrics: SpeechPcmPlaybackMetrics): void {
  window.dispatchEvent(new CustomEvent("maverick:speech-playback-metrics", { detail: metrics }));
}

function audioContextConstructor(): AudioContextConstructor | null {
  const scope = globalThis as typeof globalThis & { webkitAudioContext?: AudioContextConstructor };
  return scope.AudioContext || scope.webkitAudioContext || null;
}

function isAppleMobileBrowser(navigatorObject: NavigatorWithAudioSession | null): boolean {
  if (!navigatorObject) {
    return false;
  }
  const userAgent = String(navigatorObject.userAgent || "");
  const platform = String(navigatorObject.platform || "");
  return /iPad|iPhone|iPod/i.test(userAgent)
    || (platform === "MacIntel" && Number(navigatorObject.maxTouchPoints || 0) > 1);
}

function normalizedAudioSessionType(value: unknown): string {
  const normalized = String(value || "").trim().toLowerCase();
  return /^[a-z]+(?:-[a-z]+)*$/.test(normalized)
    ? normalized.slice(0, 32)
    : "unavailable";
}
