import { postToMaverickFrame } from "../iframePolicy";

export function syncAppFrameShellLayout(frame: HTMLIFrameElement | null | undefined, isMobileLayout: boolean): boolean {
  if (!frame?.contentWindow || !frame.dataset.maverickFrameOrigin) return false;
  postToMaverickFrame(frame, {
    mobile: isMobileLayout,
    type: "maverick.shell.layout-changed",
  });
  return true;
}
