import { useEffect, useRef, useState } from "react";
import { ApiError, transcribeSpeech } from "../api/client";

const MAX_DICTATION_MS = 120000;

type DictationStatus = "idle" | "recording" | "transcribing";

export function ComposerDictationButton({
  disabled,
  onError,
  onTranscript,
  providerAppId,
  providerAvailable,
}: {
  disabled: boolean;
  onError: (message: string | null) => void;
  onTranscript: (text: string) => void;
  providerAppId: string;
  providerAvailable: boolean;
}) {
  const [status, setStatus] = useState<DictationStatus>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordingChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  const providerDisabled = !providerAppId || providerAvailable === false;
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
      recorderRef.current?.stop();
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
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = supportedRecordingMimeType();
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
      recordingTimerRef.current = window.setTimeout(() => recorder.stop(), MAX_DICTATION_MS);
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
      const audioBase64 = await blobToBase64(audioBlob);
      const result = await transcribeSpeech(providerAppId, audioBase64, contentType);
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

function supportedRecordingMimeType(): string {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  for (const mimeType of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    if (MediaRecorder.isTypeSupported(mimeType)) {
      return mimeType;
    }
  }
  return "";
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Unable to read audio blob."));
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.readAsDataURL(blob);
  });
}
