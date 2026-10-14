import { postToLoopinoFrame } from "../iframePolicy";

export function syncAppFrameShellLayout(frame: HTMLIFrameElement | null | undefined, isMobileLayout: boolean): boolean {
  if (!frame?.contentWindow || !frame.dataset.loopinoFrameOrigin) return false;
  postToLoopinoFrame(frame, {
    mobile: isMobileLayout,
    type: "loopino.shell.layout-changed",
  });
  return true;
}
