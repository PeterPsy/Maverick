export const VITE_MAVERICK_FEATURE_GROUP_CHAT = "VITE_MAVERICK_FEATURE_GROUP_CHAT";

export function isGroupChatComposerModeEnabled(): boolean {
  return import.meta.env.VITE_MAVERICK_FEATURE_GROUP_CHAT === "1";
}
