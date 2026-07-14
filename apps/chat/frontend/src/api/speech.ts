import { requestJson } from "./http";
import type {
  SpeechCapabilitiesPayload,
  SpeechSynthesizeOptions,
  SpeechSynthesizePayload,
  SpeechTranscribeOptions,
  SpeechTranscribePayload,
} from "./types";

export function getSpeechCapabilities(providerAppId: string): Promise<SpeechCapabilitiesPayload> {
  return requestJson<SpeechCapabilitiesPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "capabilities" }),
  });
}

export function synthesizeSpeech(providerAppId: string, text: string, options: SpeechSynthesizeOptions = {}): Promise<SpeechSynthesizePayload> {
  const body: Record<string, string> = { action: "synthesize", text };
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

export function prewarmSpeechSynthesisWorker(providerAppId: string): Promise<unknown> {
  return requestJson<unknown>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "prewarm_synthesis_worker" }),
  });
}

export function prewarmSpeechWorker(providerAppId: string): Promise<unknown> {
  return requestJson<unknown>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "prewarm_worker" }),
  });
}

export function transcribeSpeech(
  providerAppId: string,
  audioBase64: string,
  contentType: string,
  optionsOrLanguage?: SpeechTranscribeOptions | string,
): Promise<SpeechTranscribePayload> {
  const body: Record<string, string> = { action: "transcribe_audio", audio_base64: audioBase64, content_type: contentType };
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
