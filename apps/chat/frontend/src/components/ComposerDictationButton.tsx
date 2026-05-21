import { useEffect, useRef, useState } from "react";
import { ApiError, transcribeSpeechBlob } from "../api/client";

const DEFAULT_MAX_DICTATION_MS = 120000;
const DEFAULT_MAX_DICTATION_AUDIO_BYTES = 700_000;
const DICTATION_TRANSCRIPTION_PROFILE = "fast";
const ADAPTIVE_LANGUAGE_PROBABILITY = 0.8;
const ADAPTIVE_LANGUAGE_HINT_USES = 1;
const MICROPHONE_AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  autoGainControl: true,
  echoCancellation: true,
  noiseSuppression: true,
};

type DictationStatus = "idle" | "recording" | "transcribing";
type AdaptiveLanguageHint = {
  language: string;
  usesRemaining: number;
};

export function ComposerDictationButton({
  disabled,
  maxAudioBytes = DEFAULT_MAX_DICTATION_AUDIO_BYTES,
  maxDurationSeconds = DEFAULT_MAX_DICTATION_MS / 1000,
  onError,
  onTranscript,
  providerAppId,
  providerAvailable,
  supportedContentTypes = [],
}: {
  disabled: boolean;
  maxAudioBytes?: number;
  maxDurationSeconds?: number;
  onError: (message: string | null) => void;
  onTranscript: (text: string) => void;
  providerAppId: string;
  providerAvailable: boolean;
  supportedContentTypes?: string[];
}) {
  const [status, setStatus] = useState<DictationStatus>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  const adaptiveLanguageRef = useRef<AdaptiveLanguageHint>({ language: "", usesRemaining: 0 });
  const providerDisabled = !providerAppId || providerAvailable === false;
  const effectiveMaxAudioBytes = Number.isFinite(maxAudioBytes) && maxAudioBytes > 0 ? maxAudioBytes : DEFAULT_MAX_DICTATION_AUDIO_BYTES;
  const effectiveMaxDurationSeconds = Number.isFinite(maxDurationSeconds) && maxDurationSeconds > 0 ? maxDurationSeconds : DEFAULT_MAX_DICTATION_MS / 1000;
  const isRecording = status === "recording";
  const isTranscribing = status === "transcribing";
  const title = isRecording ? "Stop dictation" : isTranscribing ? "Transcribing" : "Dictate";
  const disabledTitle = disabled ? "Chat is not ready for dictation" : providerDisabled ? providerDisabledMessage(providerAppId, providerAvailable) : title;

  useEffect(
    () => () => {
      stopRecordingTimer();
      stopMediaStream();
    },
    [],
  );

  async function toggleDictation() {
    if (status === "recording") {
      stopRecorderSafely(recorderRef.current);
      return;
    }
    if (status === "transcribing") {
      return;
    }
    onError(null);
    if (providerDisabled) {
      onError(providerDisabledMessage(providerAppId, providerAvailable));
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      onError("Microphone recording is not supported in this browser.");
      return;
    }
    if (window.isSecureContext === false) {
      onError("Microphone access requires HTTPS or a trusted localhost session.");
      return;
    }
    const permissionState = await microphonePermissionState();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: MICROPHONE_AUDIO_CONSTRAINTS });
      const mimeType = supportedRecordingMimeType(supportedContentTypes);
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaStreamRef.current = stream;
      recorderRef.current = recorder;
      recordingChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordingChunksRef.current.push(event.data);
        }
      };
      recorder.onerror = (event) => {
        onError(mediaRecorderErrorMessage(event));
        stopRecordingTimer();
        stopMediaStream();
        setStatus("idle");
      };
      recorder.onstop = () => {
        void finishDictation(recorder.mimeType || mimeType || "audio/webm");
      };
      recorder.start();
      setStatus("recording");
      recordingTimerRef.current = window.setTimeout(() => stopRecorderSafely(recorder), maxDurationMs(effectiveMaxDurationSeconds));
    } catch (error) {
      stopRecordingTimer();
      stopMediaStream();
      setStatus("idle");
      onError(microphoneRequestErrorMessage(error, permissionState));
    }
  }

  async function finishDictation(contentType: string) {
    stopRecordingTimer();
    stopMediaStream();
    const chunks = recordingChunksRef.current;
    recordingChunksRef.current = [];
    recorderRef.current = null;
    if (!chunks.length) {
      setStatus("idle");
      onError("No microphone audio was captured.");
      return;
    }
    setStatus("transcribing");
    try {
      const audioBlob = new Blob(chunks, { type: contentType });
      if (audioBlob.size > effectiveMaxAudioBytes) {
        setStatus("idle");
        onError(`Microphone audio is too large to transcribe. Keep recordings under ${formatBytes(effectiveMaxAudioBytes)}.`);
        return;
      }
      const languageHint = adaptiveLanguageForRequest(adaptiveLanguageRef.current);
      const result = await transcribeSpeechBlob(providerAppId, audioBlob, {
        language: languageHint || undefined,
        profile: DICTATION_TRANSCRIPTION_PROFILE,
      });
      adaptiveLanguageRef.current = nextAdaptiveLanguageHint({
        current: adaptiveLanguageRef.current,
        detectedLanguage: result.language,
        languageHint,
        probability: result.language_probability,
        transcript: result.text,
      });
      onTranscript(result.text || "");
      setStatus("idle");
    } catch (error) {
      setStatus("idle");
      onError(transcriptionErrorMessage(error));
    }
  }

  function stopRecordingTimer() {
    if (recordingTimerRef.current !== null) {
      window.clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  }

  function stopMediaStream() {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  }

  return (
    <button
      aria-label={title}
      aria-pressed={isRecording}
      className={`chatapp-composer__tool-button chatapp-composer__dictation ${isRecording ? "is-recording" : ""} ${
        isTranscribing ? "is-transcribing" : ""
      }`}
      disabled={disabled || providerDisabled || isTranscribing}
      onClick={toggleDictation}
      title={disabled || providerDisabled ? disabledTitle : title}
      type="button"
    >
      <span aria-hidden="true" className="material-symbols-rounded">
        {isTranscribing ? "hourglass_empty" : isRecording ? "stop_circle" : "mic"}
      </span>
    </button>
  );
}

function adaptiveLanguageForRequest(current: AdaptiveLanguageHint): string {
  return current.usesRemaining > 0 ? current.language : "";
}

function nextAdaptiveLanguageHint({
  current,
  detectedLanguage,
  languageHint,
  probability,
  transcript,
}: {
  current: AdaptiveLanguageHint;
  detectedLanguage: string | undefined;
  languageHint: string;
  probability: number | undefined;
  transcript: string | undefined;
}): AdaptiveLanguageHint {
  if (!String(transcript || "").trim()) {
    return { language: "", usesRemaining: 0 };
  }
  const highConfidenceLanguage = highConfidenceAdaptiveLanguage(detectedLanguage, probability);
  if (!languageHint) {
    return highConfidenceLanguage ? { language: highConfidenceLanguage, usesRemaining: ADAPTIVE_LANGUAGE_HINT_USES } : { language: "", usesRemaining: 0 };
  }
  if (highConfidenceLanguage && highConfidenceLanguage !== current.language) {
    return { language: highConfidenceLanguage, usesRemaining: ADAPTIVE_LANGUAGE_HINT_USES };
  }
  const usesRemaining = Math.max(0, current.usesRemaining - 1);
  return usesRemaining > 0 ? { language: current.language, usesRemaining } : { language: "", usesRemaining: 0 };
}

function highConfidenceAdaptiveLanguage(language: string | undefined, probability: number | undefined): string {
  const normalizedLanguage = String(language || "").trim().toLowerCase();
  const confidence = typeof probability === "number" ? probability : 0;
  if (isSupportedAdaptiveLanguage(normalizedLanguage) && confidence >= ADAPTIVE_LANGUAGE_PROBABILITY) {
    return normalizedLanguage;
  }
  return "";
}

function isSupportedAdaptiveLanguage(language: string): boolean {
  return /^[a-z]{2,3}$/.test(language);
}

async function microphonePermissionState(): Promise<PermissionState | "unknown"> {
  if (!navigator.permissions?.query) {
    return "unknown";
  }
  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    return status.state;
  } catch {
    return "unknown";
  }
}

function providerDisabledMessage(providerAppId: string, providerAvailable: boolean): string {
  if (!providerAppId) {
    return "Speech transcription provider is not selected for Chat.";
  }
  if (providerAvailable === false) {
    return "Speech transcription provider is selected but not available.";
  }
  return "Speech transcription is unavailable.";
}

function microphoneRequestErrorMessage(error: unknown, permissionState: PermissionState | "unknown"): string {
  const name = domErrorName(error);
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    if (microphoneBlockedByFramePolicy()) {
      return "Maverick shell is blocking microphone access for Chat. Hard refresh the full Maverick page, then try again.";
    }
    if (permissionState === "denied") {
      return "Microphone permission was denied by the browser. Allow microphone access in browser site settings, then reload Maverick.";
    }
    return "Microphone permission was blocked. Use the browser site settings to allow microphone access for Maverick, then try again.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No microphone device was found by the browser.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "The microphone is already in use or cannot be read by the browser.";
  }
  if (name === "OverconstrainedError") {
    return "The browser could not find a microphone matching the requested audio settings.";
  }
  return "Microphone permission was denied or unavailable.";
}

function mediaRecorderErrorMessage(event: Event): string {
  const error = "error" in event ? (event as ErrorEvent).error : null;
  const detail = error instanceof Error && error.message ? ` ${error.message}` : "";
  return `Unable to record microphone audio.${detail}`;
}

function transcriptionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `Speech transcription request failed (${error.status}): ${error.message}`;
  }
  if (error instanceof Error && error.message) {
    return `Unable to transcribe microphone audio: ${error.message}`;
  }
  return "Unable to transcribe microphone audio.";
}

function domErrorName(error: unknown): string {
  return error && typeof error === "object" && "name" in error ? String(error.name || "") : "";
}

function microphoneBlockedByFramePolicy(): boolean {
  const policyDocument = document as Document & {
    featurePolicy?: { allowsFeature(feature: string): boolean };
    permissionsPolicy?: { allowsFeature(feature: string): boolean };
  };
  try {
    if (policyDocument.permissionsPolicy) {
      return !policyDocument.permissionsPolicy.allowsFeature("microphone");
    }
    if (policyDocument.featurePolicy) {
      return !policyDocument.featurePolicy.allowsFeature("microphone");
    }
  } catch {
    return false;
  }
  return false;
}

function supportedRecordingMimeType(supportedContentTypes: string[]): string {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  const supported = new Set(supportedContentTypes.map((item) => item.split(";", 1)[0].trim().toLowerCase()).filter(Boolean));
  for (const mimeType of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    const baseType = mimeType.split(";", 1)[0];
    if ((!supported.size || supported.has(baseType)) && MediaRecorder.isTypeSupported(mimeType)) {
      return mimeType;
    }
  }
  return "";
}

function maxDurationMs(maxDurationSeconds: number): number {
  const seconds = Number.isFinite(maxDurationSeconds) && maxDurationSeconds > 0 ? maxDurationSeconds : DEFAULT_MAX_DICTATION_MS / 1000;
  return Math.max(1, Math.floor(seconds * 1000));
}

function stopRecorderSafely(recorder: MediaRecorder | null) {
  if (!recorder || recorder.state === "inactive") {
    return;
  }
  try {
    recorder.stop();
  } catch {
    // The browser may mark a recorder inactive between the state check and stop().
  }
}

function formatBytes(bytes: number): string {
  if (bytes >= 1_000_000) {
    return `${(bytes / 1_000_000).toFixed(bytes % 1_000_000 === 0 ? 0 : 1)} MB`;
  }
  return `${Math.max(1, Math.floor(bytes / 1000))} KB`;
}
