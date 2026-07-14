const AUDIO_PLAY_START_TIMEOUT_MS = 8000;
const AUDIO_CHUNK_END_TIMEOUT_MS = 180000;

export function audioCompletion(audio: HTMLAudioElement): { cancel: () => void; promise: Promise<void> } {
  let timeout: number | null = null;
  let settled = false;
  const clearCompletion = () => {
    if (timeout !== null) {
      window.clearTimeout(timeout);
      timeout = null;
    }
  };
  const promise = new Promise<void>((resolve, reject) => {
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      clearCompletion();
      resolve();
    };
    const fail = (message: string) => {
      if (settled) {
        return;
      }
      settled = true;
      clearCompletion();
      reject(new Error(message));
    };
    audio.onended = finish;
    audio.onerror = () => fail("Browser audio playback failed.");
    timeout = window.setTimeout(() => fail("Audio playback did not finish."), AUDIO_CHUNK_END_TIMEOUT_MS);
    if (audio.ended) {
      finish();
    }
  });
  return {
    cancel: () => {
      settled = true;
      clearCompletion();
    },
    promise,
  };
}

export function playAudioWithTimeout(audio: HTMLAudioElement): Promise<void> {
  const playback = audio.play();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      reject(new Error("Audio playback did not start."));
    }, AUDIO_PLAY_START_TIMEOUT_MS);
    playback.then(
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      (error) => {
        window.clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

export function speechPlaybackErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    if (error.name === "NotAllowedError") {
      return "Browser blocked speech playback. Click read aloud again.";
    }
    if (error.name === "ApiError") {
      return `Speech synthesis failed: ${error.message}`;
    }
    return `Speech playback failed: ${error.message}`;
  }
  return "Speech playback failed.";
}
