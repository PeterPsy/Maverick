import { ApiError, requestJson } from "./http";
import type {
  SpeechCapabilitiesPayload,
  SpeechSynthesizeOptions,
  SpeechSynthesizePayload,
  SpeechTranscribeOptions,
  SpeechTranscribePayload,
} from "./types";

const SYNTHESIS_SECRET_NAMES = ["deepinfra-api-key", "openrouter-api-key"];
const CAPABILITY_SECRET_NAMES = ["deepgram-api-key", ...SYNTHESIS_SECRET_NAMES];

export function getSpeechCapabilities(providerAppId: string): Promise<SpeechCapabilitiesPayload> {
  return requestJson<SpeechCapabilitiesPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(withOptionalSpeechSecrets({ action: "capabilities" }, CAPABILITY_SECRET_NAMES)),
  });
}

export function synthesizeSpeech(providerAppId: string, text: string, options: SpeechSynthesizeOptions = {}): Promise<SpeechSynthesizePayload> {
  const body: Record<string, unknown> = withOptionalSpeechSecrets({ action: "synthesize", text }, SYNTHESIS_SECRET_NAMES);
  if (options.language) {
    body.language = options.language;
  }
  if (options.voice) {
    body.voice = options.voice;
  }
  return requestJson<SpeechSynthesizePayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: options.signal,
  });
}

export async function synthesizeSpeechStream(
  providerAppId: string,
  text: string,
  options: SpeechSynthesizeOptions = {},
): Promise<Response> {
  const path = `/api/apps/${encodeURIComponent(providerAppId)}/backend`;
  const body: Record<string, unknown> = withOptionalSpeechSecrets({
    action: "synthesize",
    format: "pcm",
    response_mode: "stream",
    text,
  }, SYNTHESIS_SECRET_NAMES);
  if (options.language) {
    body.language = options.language;
  }
  if (options.voice) {
    body.voice = options.voice;
  }
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "audio/pcm", "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: options.signal,
  });
  if (!response.ok) {
    let detail = `Request failed ${response.status}: ${path}`;
    try {
      const payload = (await response.json()) as { detail?: string; error?: string };
      detail = payload.detail || payload.error || detail;
    } catch {
      // Keep the HTTP fallback detail.
    }
    throw new ApiError(detail, { path, status: response.status });
  }
  const contentType = response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase();
  if (contentType !== "audio/pcm" || !response.body) {
    throw new ApiError("Speech provider did not return a PCM audio stream.", { path, status: response.status });
  }
  return response;
}

export function prewarmSpeechSynthesisWorker(providerAppId: string): Promise<unknown> {
  return requestJson<unknown>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(withOptionalSpeechSecrets({ action: "prewarm_synthesis_worker" }, [])),
  });
}

export function prewarmSpeechWorker(providerAppId: string): Promise<unknown> {
  return requestJson<unknown>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(withOptionalSpeechSecrets({ action: "prewarm_worker" }, [])),
  });
}

export function recordSpeechPlaybackMetrics(
  providerAppId: string,
  metrics: Record<string, unknown>,
): Promise<unknown> {
  return requestJson<unknown>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(withOptionalSpeechSecrets({ action: "record_playback_metrics", ...metrics }, [])),
  });
}

export function transcribeSpeech(
  providerAppId: string,
  audioBase64: string,
  contentType: string,
  optionsOrLanguage?: SpeechTranscribeOptions | string,
): Promise<SpeechTranscribePayload> {
  const body: Record<string, unknown> = withOptionalSpeechSecrets(
    { action: "transcribe_audio", audio_base64: audioBase64, content_type: contentType },
    ["deepgram-api-key"],
  );
  const options = typeof optionsOrLanguage === "string" ? { language: optionsOrLanguage } : optionsOrLanguage || {};
  if (options.language) {
    body.language = options.language;
  }
  if (options.profile) {
    body.profile = options.profile;
  }
  if (options.sessionId) {
    body.session_id = options.sessionId;
  }
  if (typeof options.chunkIndex === "number") {
    body.chunk_index = String(options.chunkIndex);
  }
  if (typeof options.final === "boolean") {
    body.final = options.final ? "true" : "false";
  }
  if (typeof options.conversation === "boolean") {
    body.conversation = options.conversation ? "true" : "false";
  }
  if (typeof options.dictation === "boolean") {
    body.dictation = options.dictation ? "true" : "false";
  }
  return requestJson<SpeechTranscribePayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function transcribeSpeechBlob(
  providerAppId: string,
  audioBlob: Blob,
  optionsOrLanguage?: SpeechTranscribeOptions | string,
): Promise<SpeechTranscribePayload> {
  const options = typeof optionsOrLanguage === "string" ? { language: optionsOrLanguage } : optionsOrLanguage || {};
  const params = new URLSearchParams({ action: "transcribe_audio" });
  params.set(
    "_app_secret_request",
    JSON.stringify({ logical_names: ["deepgram-api-key"], required: false }),
  );
  if (options.language) {
    params.set("language", options.language);
  }
  if (options.profile) {
    params.set("profile", options.profile);
  }
  if (options.sessionId) {
    params.set("session_id", options.sessionId);
  }
  if (typeof options.chunkIndex === "number") {
    params.set("chunk_index", String(options.chunkIndex));
  }
  if (typeof options.final === "boolean") {
    params.set("final", options.final ? "true" : "false");
  }
  if (typeof options.conversation === "boolean") {
    params.set("conversation", options.conversation ? "true" : "false");
  }
  if (typeof options.dictation === "boolean") {
    params.set("dictation", options.dictation ? "true" : "false");
  }
  return requestJson<SpeechTranscribePayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": audioBlob.type || "application/octet-stream" },
    body: audioBlob,
  });
}

function withOptionalSpeechSecrets(body: Record<string, unknown>, logicalNames: string[]): Record<string, unknown> {
  return {
    ...body,
    _app_secret_request: {
      logical_names: logicalNames,
      required: false,
    },
  };
}
