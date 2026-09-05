import type { RuntimeEvent, RuntimeSession, RuntimeTurn } from "../api/client";

export type RuntimeTranscriptCacheEntry = {
  activeSession: RuntimeSession | null;
  activeTurn: RuntimeTurn | null;
  events: RuntimeEvent[];
  hasLoadedHistory: boolean;
  hasMoreHistory?: boolean;
};
