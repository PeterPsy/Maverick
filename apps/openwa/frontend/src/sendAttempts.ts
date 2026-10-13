import { useEffect, useRef, useState } from "react";
import type { Message } from "./api";

export interface SendAttempt {
  text: string;
  quote?: Message;
  key: string;
  createdAt: number;
  state: "retryable" | "in_progress" | "unknown";
  error: string;
}

// The provider expires keys after 24 hours. Leave a margin for a retry in flight.
export function retryBlocked(attempt: SendAttempt | null): boolean {
  return !!attempt && (attempt.state === "unknown" || Date.now() - attempt.createdAt >= 23 * 60 * 60 * 1000);
}

export function sendAttemptKey(scope: string, session: string, chat: string): string {
  return "openwa.send." + JSON.stringify([scope, session, chat]);
}

function load(key: string): { attempt: SendAttempt | null; storageError: string } {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { attempt: null, storageError: "" };
    const attempt = JSON.parse(raw) as SendAttempt;
    if (!attempt || typeof attempt.text !== "string" || !attempt.text.trim() || attempt.text.length > 4096 ||
      typeof attempt.key !== "string" || !/^[A-Za-z0-9_-]{12,100}$/.test(attempt.key) ||
      !Number.isFinite(attempt.createdAt) || attempt.createdAt <= 0 ||
      !["retryable", "in_progress", "unknown"].includes(attempt.state) || typeof attempt.error !== "string" ||
      (attempt.quote && typeof attempt.quote.waMessageId !== "string")) {
      throw new Error("Invalid saved send attempt");
    }
    return { attempt, storageError: "" };
  } catch {
    return { attempt: null, storageError: "The saved send attempt could not be read. Restore browser storage before sending." };
  }
}

export function useSendAttempt(key: string) {
  const [saved, setSaved] = useState(() => load(key));
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  function save(attempt: SendAttempt | null): boolean {
    try {
      if (attempt) localStorage.setItem(key, JSON.stringify(attempt));
      else localStorage.removeItem(key);
      if (mounted.current) setSaved({ attempt, storageError: "" });
      return true;
    } catch {
      if (mounted.current) setSaved((previous) => ({ ...previous,
        storageError: "The send attempt could not be saved. Restore browser storage before sending." }));
      return false;
    }
  }
  return { ...saved, save, mounted };
}
