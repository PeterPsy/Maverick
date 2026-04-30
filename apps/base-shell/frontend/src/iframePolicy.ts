export const MAVERICK_IFRAME_SANDBOX = "allow-downloads allow-forms allow-popups allow-same-origin allow-scripts";

export function postToMaverickFrame(frame: HTMLIFrameElement | null | undefined, message: unknown) {
  if (!frame?.contentWindow) {
    return;
  }
  try {
    frame.contentWindow.postMessage(message, window.location.origin);
  } catch (error) {
    if (error instanceof DOMException) {
      frame.contentWindow.postMessage(message, "*");
      return;
    }
    throw error;
  }
}

export function postMaverickFrameVisibility(
  frame: HTMLIFrameElement | null | undefined,
  payload: {
    app_id?: string;
    owner_app_id?: string;
    visible: boolean;
    widget_id?: string;
  },
) {
  postToMaverickFrame(frame, {
    type: "maverick.app.visibility-changed",
    ...payload,
  });
}
