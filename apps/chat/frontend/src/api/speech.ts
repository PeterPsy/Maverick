import { requestJson } from "./http";
import type { SpeechCapabilitiesPayload, SpeechSynthesizePayload, SpeechTranscribeOptions, SpeechTranscribePayload } from "./types";

export function getSpeechCapabilities(providerAppId: string): Promise<SpeechCapabilitiesPayload> {
  return requestJson<SpeechCapabilitiesPayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "capabilities" }),
  });
}

export function synthesizeSpeech(providerAppId: string, text: string): Promise<SpeechSynthesizePayload> {
  return requestJson<SpeechSynthesizePayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "synthesize", text }),
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
  return requestJson<SpeechTranscribePayload>(`/api/apps/${encodeURIComponent(providerAppId)}/backend?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": audioBlob.type || "application/octet-stream" },
    body: audioBlob,
  });
}
