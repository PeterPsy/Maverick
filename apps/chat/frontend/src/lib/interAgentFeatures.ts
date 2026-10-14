export const VITE_LOOPINO_FEATURE_GROUP_CHAT = "VITE_LOOPINO_FEATURE_GROUP_CHAT";

export function isGroupChatComposerModeEnabled(): boolean {
  return import.meta.env.VITE_LOOPINO_FEATURE_GROUP_CHAT === "1";
}
