import { MAX_FLOATING_CHAT_WIDTH_PX, MAX_SIDEBAR_DETAILS_WIDTH_PX, MIN_FLOATING_CHAT_WIDTH_PX, MIN_SIDEBAR_DETAILS_WIDTH_PX } from "../session";

export const MIN_WORKSPACE_WIDTH_PX = 560;

/** Reserve the workspace first; saved widths remain preferences across resize. */
export function resolvePanelLayout({ viewportWidth, rootFontSize, railWidthRem, sidebarFixed, chatFixed, sidebarWidth, chatWidth }: {
  viewportWidth: number; rootFontSize: number; railWidthRem: number;
  sidebarFixed: boolean; chatFixed: boolean; sidebarWidth: number; chatWidth: number;
}) {
  const railSpace = (railWidthRem + 2.14) * rootFontSize;
  const budget = Math.max(0, viewportWidth - railSpace - MIN_WORKSPACE_WIDTH_PX);
  const dockSpace = 1.5 * rootFontSize;
  let fixedSidebar = sidebarFixed;
  let fixedChat = chatFixed;
  if (fixedChat && budget < MIN_FLOATING_CHAT_WIDTH_PX + dockSpace) fixedChat = false;
  if (fixedSidebar && budget < MIN_SIDEBAR_DETAILS_WIDTH_PX + (fixedChat ? MIN_FLOATING_CHAT_WIDTH_PX + dockSpace : 0)) fixedSidebar = false;
  const effectiveSidebarWidth = fixedSidebar
    ? Math.floor(Math.min(MAX_SIDEBAR_DETAILS_WIDTH_PX, sidebarWidth, budget - (fixedChat ? MIN_FLOATING_CHAT_WIDTH_PX + dockSpace : 0)))
    : sidebarWidth;
  const effectiveChatWidth = fixedChat
    ? Math.floor(Math.min(MAX_FLOATING_CHAT_WIDTH_PX, chatWidth, budget - (fixedSidebar ? effectiveSidebarWidth : 0) - dockSpace))
    : chatWidth;
  return { fixedSidebar, fixedChat, sidebarWidth: effectiveSidebarWidth, chatWidth: effectiveChatWidth };
}
