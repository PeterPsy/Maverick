import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { createWidgetContext, listWidgets, WidgetRegistryItem } from "../api";
import { MAVERICK_IFRAME_SANDBOX, postMaverickFrameVisibility, postToMaverickFrame } from "../iframePolicy";
import { widgetSelectionChangedMessage } from "../lib/widgetSelectionMessages";

type CaptureRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

export function WidgetSlot({
  activeAppId,
  activeWorkspaceId,
  content,
  contentKind,
  hostAppId,
  label,
  onCloseSidebar,
  onOpenApp,
  preferredOwnerAppId,
  size = "fill",
}: {
  activeAppId?: string | null;
  activeWorkspaceId: string;
  content: Record<string, unknown>;
  contentKind: string;
  hostAppId: string;
  label: string;
  onCloseSidebar?: () => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  preferredOwnerAppId?: string | null;
  size?: "compact" | "fill" | "overlay";
}) {
  const [widget, setWidget] = useState<WidgetRegistryItem | null>(null);
  const [contextToken, setContextToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overlaySize, setOverlaySize] = useState({ height: "3rem", width: "3rem" });
  const [captureDraft, setCaptureDraft] = useState<CaptureRect | null>(null);
  const [captureStart, setCaptureStart] = useState<{ x: number; y: number } | null>(null);
  const [isCaptureActive, setIsCaptureActive] = useState(false);
  const [isCaptureBusy, setIsCaptureBusy] = useState(false);
  const [frameRevision, setFrameRevision] = useState(0);
  const captureStreamRef = useRef<MediaStream | null>(null);
  const captureNavigationScopeRef = useRef("");
  const captureVideoRef = useRef<HTMLVideoElement | null>(null);
  const widgetFrameRef = useRef<HTMLIFrameElement | null>(null);
  const contentSignature = JSON.stringify({ activeWorkspaceId, content });

  useEffect(() => {
    let cancelled = false;
    setWidget(null);
    setContextToken(null);
    setError(null);
    setOverlaySize({ height: "3rem", width: "3rem" });

    async function loadWidget() {
      try {
        const registry = await listWidgets(hostAppId, contentKind);
        const selected = selectPreferredWidget(registry.items, preferredOwnerAppId);
        if (!selected) {
          if (!cancelled) {
            setWidget(null);
            setContextToken(null);
          }
          return;
        }
        const context = await createWidgetContext({
          host_app_id: hostAppId,
          owner_app_id: selected.owner_app_id,
          widget_id: selected.widget_id,
          message_id: `${activeWorkspaceId}:${hostAppId}:${contentKind}`,
          content: { kind: contentKind, workspace_id: activeWorkspaceId, payload: content },
        });
        if (!cancelled) {
          setWidget(selected);
          setContextToken(context.context_token);
          setError(null);
        }
      } catch (loadError) {
        if (!cancelled) {
          setWidget(null);
          setContextToken(null);
          setError(loadError instanceof Error ? loadError.message : "Widget non disponibile.");
        }
      }
    }

    loadWidget();
    return () => {
      cancelled = true;
    };
  }, [activeWorkspaceId, contentKind, hostAppId, preferredOwnerAppId, size]);

  function postWidgetContextChanged() {
    if (!widget) {
      return;
    }
    postWidgetVisibility();
    postToMaverickFrame(
      widgetFrameRef.current,
      {
        type: "maverick.widget.context-changed",
        context: { content: { kind: contentKind, workspace_id: activeWorkspaceId, payload: content } },
        owner_app_id: widget.owner_app_id,
        widget_id: widget.widget_id,
      },
    );
  }

  function postWidgetVisibility() {
    if (!widget) {
      return;
    }
    const visible = size !== "overlay" || !(overlaySize.width === "3rem" && overlaySize.height === "3rem");
    postMaverickFrameVisibility(widgetFrameRef.current, {
      owner_app_id: widget.owner_app_id,
      visible,
      widget_id: widget.widget_id,
    });
  }

  useEffect(() => {
    postWidgetContextChanged();
  }, [activeWorkspaceId, contentKind, contentSignature, widget?.owner_app_id, widget?.widget_id]);

  useEffect(() => {
    postWidgetVisibility();
  }, [overlaySize.height, overlaySize.width, size, widget?.owner_app_id, widget?.widget_id]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        active_thread_id?: string;
        app_id?: string;
        height?: string;
        owner_app_id?: string;
        navigation_scope?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        selection?: Record<string, string | boolean | null>;
        type?: string;
        widget_id?: string;
        width?: string;
        workspace_id?: string;
      };
      if (
        payload.type === "maverick.app.frontend-changed" &&
        payload.owner_app_id === widget?.owner_app_id &&
        (!payload.workspace_id || payload.workspace_id === activeWorkspaceId)
      ) {
        setFrameRevision((current) => current + 1);
        return;
      }
      if (payload.type === "maverick.widget.open-app" && payload.app_id) {
        onOpenApp(payload.app_id, payload.params);
      }
      if (payload.type === "maverick.shell.sidebar.close") {
        onCloseSidebar?.();
      }
      if (
        payload.type === "maverick.shell.capture-area.start" &&
        size === "overlay" &&
        payload.owner_app_id === widget?.owner_app_id &&
        payload.widget_id === widget?.widget_id
      ) {
        const nextNavigationScope = typeof payload.navigation_scope === "string" ? payload.navigation_scope : "";
        captureNavigationScopeRef.current = nextNavigationScope;
        void startCaptureSession();
      }
      if (
        payload.type === "maverick.widget.resize" &&
        size === "overlay" &&
        payload.owner_app_id === widget?.owner_app_id &&
        payload.widget_id === widget?.widget_id
      ) {
        const width = typeof payload.width === "string" && payload.width ? payload.width : "3rem";
        const height = typeof payload.height === "string" && payload.height ? payload.height : "3rem";
        setOverlaySize({ height, width });
      }
      if (payload.type === "maverick.chat.active-thread-changed" && payload.owner_app_id === widget?.owner_app_id) {
        postToMaverickFrame(
          widgetFrameRef.current,
          {
            type: "maverick.chat.active-thread-changed",
            active_thread_id: typeof payload.active_thread_id === "string" ? payload.active_thread_id : "",
            navigation_scope: typeof payload.navigation_scope === "string" ? payload.navigation_scope : "",
            owner_app_id: payload.owner_app_id,
          },
        );
      }
      const selectionMessage = widgetSelectionChangedMessage(payload, widget?.owner_app_id);
      if (selectionMessage) {
        postToMaverickFrame(widgetFrameRef.current, selectionMessage);
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === widget?.owner_app_id) {
        postToMaverickFrame(
          widgetFrameRef.current,
          {
            type: "maverick.widget.data-changed",
            active_thread_id: typeof payload.active_thread_id === "string" ? payload.active_thread_id : "",
            navigation_scope: typeof payload.navigation_scope === "string" ? payload.navigation_scope : "",
            owner_app_id: payload.owner_app_id,
            resource: payload.resource || "",
          },
        );
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onCloseSidebar, onOpenApp, size, widget?.owner_app_id, widget?.widget_id]);

  function postCaptureError(message: string) {
    postToMaverickFrame(
      widgetFrameRef.current,
      {
        type: "maverick.widget.capture-area.error",
        error: message,
        navigation_scope: captureNavigationScopeRef.current,
      },
    );
  }

  function postCaptureFile(file: File) {
    postToMaverickFrame(
      widgetFrameRef.current,
      {
        type: "maverick.widget.capture-area.complete",
        files: [file],
        navigation_scope: captureNavigationScopeRef.current,
      },
    );
  }

  async function finishCapture(rect: CaptureRect) {
    if (rect.width < 8 || rect.height < 8) {
      setIsCaptureActive(false);
      return;
    }
    setIsCaptureBusy(true);
    try {
      const video = captureVideoRef.current;
      if (!video) {
        throw new Error("Screen capture is not ready.");
      }
      const file = await captureViewportRect(rect, video);
      postCaptureFile(file);
    } catch (captureError) {
      postCaptureError(captureError instanceof Error ? captureError.message : "Unable to capture selected area.");
    } finally {
      cleanupCaptureMedia();
      setIsCaptureActive(false);
      setIsCaptureBusy(false);
      setCaptureDraft(null);
      setCaptureStart(null);
    }
  }

  function handleCapturePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (isCaptureBusy || event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    const start = { x: event.clientX, y: event.clientY };
    setCaptureStart(start);
    setCaptureDraft({ ...start, height: 0, width: 0 });
  }

  function handleCapturePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!captureStart || isCaptureBusy) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    setCaptureDraft(rectFromPoints(captureStart.x, captureStart.y, event.clientX, event.clientY));
  }

  function handleCapturePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (!captureStart || isCaptureBusy) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.releasePointerCapture(event.pointerId);
    void finishCapture(rectFromPoints(captureStart.x, captureStart.y, event.clientX, event.clientY));
  }

  function cancelCapture() {
    cleanupCaptureMedia();
    setIsCaptureActive(false);
    setIsCaptureBusy(false);
    setCaptureDraft(null);
    captureNavigationScopeRef.current = "";
    setCaptureStart(null);
  }

  async function startCaptureSession() {
    if (isCaptureBusy) {
      return;
    }
    cleanupCaptureMedia();
    setCaptureDraft(null);
    setCaptureStart(null);
    setIsCaptureActive(false);
    setIsCaptureBusy(true);
    try {
      const { stream, video } = await prepareCaptureStream();
      captureStreamRef.current = stream;
      captureVideoRef.current = video;
      setIsCaptureActive(true);
    } catch (captureError) {
      postCaptureError(captureError instanceof Error ? captureError.message : "Unable to start screen capture.");
    } finally {
      setIsCaptureBusy(false);
    }
  }

  function cleanupCaptureMedia() {
    captureStreamRef.current?.getTracks().forEach((track) => track.stop());
    captureStreamRef.current = null;
    captureVideoRef.current = null;
  }

  useEffect(() => {
    if (!isCaptureActive) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        cancelCapture();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isCaptureActive]);

  useEffect(() => cleanupCaptureMedia, []);

  if (!widget || !contextToken || (activeAppId && activeAppId === widget.owner_app_id)) {
    return error ? <p className="bs-widget-slot__fallback">{error}</p> : null;
  }

  const src = widgetFrameSrc(widget.frontend_mount, contextToken, frameRevision);
  const isCollapsedOverlay = size === "overlay" && overlaySize.width === "3rem" && overlaySize.height === "3rem";
  const slotStyle =
    size === "overlay"
      ? overlaySize
      : size === "compact"
        ? { height: "2.65rem", maxHeight: "2.65rem", minHeight: "2.65rem" }
        : undefined;

  return (
    <>
      <section
        className={`bs-widget-slot bs-widget-slot--${size}${isCollapsedOverlay ? " is-collapsed" : ""}`}
        aria-label={label}
        style={slotStyle}
      >
        <iframe
          className="bs-widget-slot__frame"
          key={`${activeWorkspaceId}:${widget.owner_app_id}:${widget.widget_id}:${contextToken}:${frameRevision}`}
          onLoad={postWidgetContextChanged}
          ref={widgetFrameRef}
          sandbox={MAVERICK_IFRAME_SANDBOX}
          src={src}
          title={label}
        />
      </section>
      {isCaptureActive ? (
        <div
          className={`bs-capture-overlay ${isCaptureBusy ? "is-busy" : ""}`}
          onPointerDown={handleCapturePointerDown}
          onPointerMove={handleCapturePointerMove}
          onPointerUp={handleCapturePointerUp}
          role="presentation"
        >
          <div className="bs-capture-overlay__hint">
            {isCaptureBusy ? "Preparazione screenshot..." : "Trascina per catturare un'area. Esc annulla."}
          </div>
          {captureDraft ? <div className="bs-capture-overlay__rect" style={captureRectStyle(captureDraft)} /> : null}
          <button className="bs-capture-overlay__cancel" onClick={cancelCapture} onPointerDown={(event) => event.stopPropagation()} type="button">
            Annulla
          </button>
        </div>
      ) : null}
    </>
  );
}

export function selectPreferredWidget(
  widgets: WidgetRegistryItem[],
  preferredOwnerAppId?: string | null,
): WidgetRegistryItem | null {
  if (!preferredOwnerAppId) {
    return widgets[0] || null;
  }
  return widgets.find((item) => item.owner_app_id === preferredOwnerAppId) || null;
}

function widgetFrameSrc(frontendMount: string, contextToken: string, revision: number): string {
  const url = new URL(frontendMount, window.location.origin);
  if (revision > 0) {
    url.searchParams.set("_maverick_refresh", String(revision));
  }
  url.hash = `context=${encodeURIComponent(contextToken)}`;
  return `${url.pathname}${url.search}${url.hash}`;
}

function rectFromPoints(startX: number, startY: number, endX: number, endY: number): CaptureRect {
  return {
    height: Math.abs(endY - startY),
    width: Math.abs(endX - startX),
    x: Math.min(startX, endX),
    y: Math.min(startY, endY),
  };
}

function captureRectStyle(rect: CaptureRect) {
  return {
    height: `${rect.height}px`,
    left: `${rect.x}px`,
    top: `${rect.y}px`,
    width: `${rect.width}px`,
  };
}

async function prepareCaptureStream(): Promise<{ stream: MediaStream; video: HTMLVideoElement }> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error("Screen capture is not available in this browser.");
  }
  const stream = await navigator.mediaDevices.getDisplayMedia({ audio: false, video: true });
  const video = document.createElement("video");
  video.srcObject = stream;
  video.muted = true;
  await video.play();
  await new Promise<void>((resolve) => {
    if (video.videoWidth && video.videoHeight) {
      resolve();
      return;
    }
    video.onloadedmetadata = () => resolve();
  });
  return { stream, video };
}

async function captureViewportRect(rect: CaptureRect, video: HTMLVideoElement): Promise<File> {
  const scaleX = video.videoWidth / window.innerWidth;
  const scaleY = video.videoHeight / window.innerHeight;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(rect.width * scaleX));
  canvas.height = Math.max(1, Math.round(rect.height * scaleY));
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Unable to prepare screenshot crop.");
  }
  context.drawImage(
    video,
    Math.round(rect.x * scaleX),
    Math.round(rect.y * scaleY),
    Math.round(rect.width * scaleX),
    Math.round(rect.height * scaleY),
    0,
    0,
    canvas.width,
    canvas.height,
  );
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((value) => (value ? resolve(value) : reject(new Error("Unable to create screenshot image."))), "image/png");
  });
  return new File([blob], `page-selection-${new Date().toISOString().replace(/[:.]/g, "-")}.png`, { type: "image/png" });
}
