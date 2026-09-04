import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { createWidgetContext, listWidgets, WidgetRegistryItem } from "../api";
import {
  MAVERICK_IFRAME_SANDBOX,
  isShellWindowMessage,
  postMaverickFrameVisibility,
  postMaverickShellTheme,
  postToMaverickFrame,
  registeredMaverickFrameOwner,
  type MaverickFrameScope,
  widgetFrameBrowserFeaturePolicy,
} from "../iframePolicy";
import { externalHttpUrlFromMessage, openExternalUrl } from "../lib/externalUrl";
import { widgetSelectionChangedMessage } from "../lib/widgetSelectionMessages";
import { measureStartupMetric } from "../startupMetrics";
import type { ShellThemeState } from "../theme";
import { DEFAULT_SHELL_THEME_STATE, shellThemeSignature, urlWithShellThemeSearchParams } from "../theme";
import { ShellPendingIndicator } from "./ShellPendingIndicator";
import { IsolatedMaverickFrame } from "./IsolatedMaverickFrame";

export type PrimaryActionPreferredSurface = "app" | "sidebar";

export type WidgetPrimaryActionState = {
  available: boolean;
  label: string;
  preferredSurface: PrimaryActionPreferredSurface;
};

const UNAVAILABLE_PRIMARY_ACTION_STATE: WidgetPrimaryActionState = {
  available: false,
  label: "",
  preferredSurface: "app",
};

const COMPACT_SLOT_DEFAULT_HEIGHT = "2.65rem";
const MAX_COMPACT_SLOT_HEIGHT_PX = 220;
const MAX_COMPACT_SLOT_HEIGHT_REM = 12;
const COLLAPSED_OVERLAY_SIZE = "3rem";
const MAX_OVERLAY_HEIGHT_PX = 2160;
const MAX_OVERLAY_WIDTH_PX = 4096;
const PIXEL_SIZE_PATTERN = /^(\d+(?:\.\d+)?)px$/;
const COMPACT_SIZE_PATTERN = /^(\d+(?:\.\d+)?)(px|rem)$/;

type CaptureRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

type WidgetMessagePayload = {
  active_thread_id?: string;
  app_id?: string;
  detail?: Record<string, unknown>;
  height?: string;
  owner_app_id?: string;
  navigation_scope?: string;
  params?: Record<string, string | boolean | null>;
  placement?: string;
  resource?: string;
  selection?: Record<string, string | boolean | null>;
  type?: string;
  url?: string;
  widget_id?: string;
  width?: string;
  workspace_id?: string;
  available?: boolean;
  label?: string;
  preferred_surface?: string;
};

export function WidgetSlot({
  activeAppId,
  activeWorkspaceId,
  content,
  contentKind,
  frameScope,
  hostAppId,
  label,
  isActive = true,
  onCloseSidebar,
  onActiveThreadChange,
  onCloseDock,
  onOpenDock,
  onOpenApp,
  onOpenSidebar,
  onPrimaryActionStateChange,
  preferredOwnerAppId,
  primaryActionRequestId = 0,
  size = "fill",
  shellTheme = DEFAULT_SHELL_THEME_STATE,
}: {
  activeAppId?: string | null;
  activeWorkspaceId: string;
  content: Record<string, unknown>;
  contentKind: string;
  frameScope: MaverickFrameScope;
  hostAppId: string;
  label: string;
  isActive?: boolean;
  onCloseDock?: () => void;
  onCloseSidebar?: () => void;
  onActiveThreadChange?: (event: { navigationScope: string; ownerAppId: string; threadId: string }) => void;
  onOpenDock?: (request: {
    navigationScope: string | null;
    ownerAppId: string;
    placement: "right";
    threadId: string | null;
    widgetId: string;
  }) => void;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  onOpenSidebar?: () => void;
  onPrimaryActionStateChange?: (state: WidgetPrimaryActionState) => void;
  preferredOwnerAppId?: string | null;
  primaryActionRequestId?: number;
  size?: "compact" | "fill" | "overlay";
  shellTheme?: ShellThemeState;
}) {
  const [widget, setWidget] = useState<WidgetRegistryItem | null>(null);
  const [contextToken, setContextToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isResolvingWidget, setIsResolvingWidget] = useState(true);
  const [loadedFrameKey, setLoadedFrameKey] = useState("");
  const [overlaySize, setOverlaySize] = useState(collapsedOverlaySize());
  const [captureDraft, setCaptureDraft] = useState<CaptureRect | null>(null);
  const [captureStart, setCaptureStart] = useState<{ x: number; y: number } | null>(null);
  const [isCaptureActive, setIsCaptureActive] = useState(false);
  const [isCaptureBusy, setIsCaptureBusy] = useState(false);
  const [compactSlotHeight, setCompactSlotHeight] = useState(COMPACT_SLOT_DEFAULT_HEIGHT);
  const [frameRevision, setFrameRevision] = useState(0);
  const captureStreamRef = useRef<MediaStream | null>(null);
  const captureNavigationScopeRef = useRef("");
  const captureVideoRef = useRef<HTMLVideoElement | null>(null);
  const lastPrimaryActionRequestRef = useRef(primaryActionRequestId);
  const shellThemeRef = useRef(shellTheme);
  const widgetFrameBootstrapThemesRef = useRef<Record<string, ShellThemeState>>({});
  const widgetFrameRef = useRef<HTMLIFrameElement | null>(null);
  const contentSignature = JSON.stringify({ activeWorkspaceId, content });
  const themeSignature = shellThemeSignature(shellTheme);
  const supportsPrimaryActionSlot = contentKind === "shell.sidebar.footer";

  useEffect(() => {
    shellThemeRef.current = shellTheme;
  }, [shellTheme]);

  useEffect(() => {
    let cancelled = false;
    setWidget(null);
    setContextToken(null);
    setError(null);
    setIsResolvingWidget(true);
    setLoadedFrameKey("");
    setOverlaySize(collapsedOverlaySize());
    setCompactSlotHeight(COMPACT_SLOT_DEFAULT_HEIGHT);
    if (supportsPrimaryActionSlot) {
      onPrimaryActionStateChange?.(UNAVAILABLE_PRIMARY_ACTION_STATE);
    }

    async function loadWidget() {
      try {
        const discoveryStartedAt = performance.now();
        const registry = await listWidgets(hostAppId, contentKind);
        measureStartupMetric("widget.discovery", discoveryStartedAt, {
          content_kind: contentKind,
          host_app_id: hostAppId,
          widget_count: registry.items.length,
        });
        const selected = selectPreferredWidget(registry.items, preferredOwnerAppId);
        if (!selected) {
          if (!cancelled) {
            setWidget(null);
            setContextToken(null);
            setIsResolvingWidget(false);
            if (supportsPrimaryActionSlot) {
              onPrimaryActionStateChange?.(UNAVAILABLE_PRIMARY_ACTION_STATE);
            }
          }
          return;
        }
        const contextStartedAt = performance.now();
        const context = await createWidgetContext({
          host_app_id: hostAppId,
          owner_app_id: selected.owner_app_id,
          widget_id: selected.widget_id,
          message_id: `${activeWorkspaceId}:${hostAppId}:${contentKind}`,
          content: themedWidgetContextContent({
            activeWorkspaceId,
            content,
            contentKind,
            shellTheme: shellThemeRef.current,
          }),
        });
        measureStartupMetric("widget.context", contextStartedAt, {
          content_kind: contentKind,
          host_app_id: hostAppId,
          owner_app_id: selected.owner_app_id,
          widget_id: selected.widget_id,
        });
        if (!cancelled) {
          setWidget(selected);
          setContextToken(context.context_token);
          setError(null);
          setIsResolvingWidget(false);
        }
      } catch (loadError) {
        if (!cancelled) {
          setWidget(null);
          setContextToken(null);
          setError(loadError instanceof Error ? loadError.message : "Widget non disponibile.");
          setIsResolvingWidget(false);
          if (supportsPrimaryActionSlot) {
            onPrimaryActionStateChange?.(UNAVAILABLE_PRIMARY_ACTION_STATE);
          }
        }
      }
    }

    loadWidget();
    return () => {
      cancelled = true;
    };
  }, [activeWorkspaceId, contentKind, hostAppId, onPrimaryActionStateChange, preferredOwnerAppId, supportsPrimaryActionSlot]);

  function postWidgetContextChanged() {
    if (!widget) {
      return;
    }
    postWidgetVisibility();
    postMaverickShellTheme(widgetFrameRef.current, shellTheme);
    postToMaverickFrame(
      widgetFrameRef.current,
      {
        type: "maverick.widget.context-changed",
        context: {
          content: themedWidgetContextContent({
            activeWorkspaceId,
            content,
            contentKind,
            shellTheme,
          }),
        },
        owner_app_id: widget.owner_app_id,
        widget_id: widget.widget_id,
      },
    );
    if (supportsPrimaryActionSlot) {
      postToMaverickFrame(
        widgetFrameRef.current,
        {
          type: "maverick.widget.primary-action.query",
          owner_app_id: widget.owner_app_id,
          widget_id: widget.widget_id,
        },
      );
    }
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
  }, [activeWorkspaceId, contentKind, contentSignature, themeSignature, widget?.owner_app_id, widget?.widget_id]);

  useEffect(() => {
    postMaverickShellTheme(widgetFrameRef.current, shellTheme);
  }, [themeSignature, widget?.owner_app_id, widget?.widget_id]);

  useEffect(() => {
    postWidgetVisibility();
  }, [overlaySize.height, overlaySize.width, size, widget?.owner_app_id, widget?.widget_id]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const senderOwnerAppId = registeredMaverickFrameOwner(event, frameScope);
      const senderIsShell = isShellWindowMessage(event);
      if (
        (!senderIsShell && !senderOwnerAppId)
        || !event.data
        || typeof event.data !== "object"
      ) {
        return;
      }
      const payload = event.data as WidgetMessagePayload;
      if (
        ["maverick.app.frontend-changed", "maverick.app.runtime-changed"].includes(payload.type || "") &&
        typeof payload.owner_app_id === "string" &&
        payload.owner_app_id === widget?.owner_app_id &&
        (senderIsShell || senderOwnerAppId === payload.owner_app_id) &&
        (!payload.workspace_id || payload.workspace_id === activeWorkspaceId)
      ) {
        setFrameRevision((current) => current + 1);
        return;
      }
      if (
        payload.type === "maverick.widget.open-app" &&
        payload.app_id &&
        isMountedWidgetFrameSource(event, widgetFrameRef.current)
      ) {
        onOpenApp(payload.app_id, payload.params);
      }
      if (
        payload.type === "maverick.widget.dock.open" &&
        payload.placement === "right" &&
        isMountedWidgetFrameMessage(event, payload, widget, widgetFrameRef.current)
      ) {
        const mountedWidget = widget;
        if (!mountedWidget) {
          return;
        }
        const params = payload.params && typeof payload.params === "object" ? payload.params : {};
        onOpenDock?.({
          navigationScope: typeof params.navigation_scope === "string" && params.navigation_scope.trim() ? params.navigation_scope.trim() : null,
          ownerAppId: mountedWidget.owner_app_id,
          placement: "right",
          threadId: typeof params.thread_id === "string" && params.thread_id.trim() ? params.thread_id.trim() : null,
          widgetId: mountedWidget.widget_id,
        });
        if (size === "overlay") {
          setOverlaySize(collapsedOverlaySize());
        }
      }
      if (
        payload.type === "maverick.widget.dock.close" &&
        isMountedWidgetFrameMessage(event, payload, widget, widgetFrameRef.current)
      ) {
        onCloseDock?.();
      }
      if (payload.type === "maverick.shell.sidebar.close" && isActiveWidgetCommand(event, widgetFrameRef.current, isActive)) {
        onCloseSidebar?.();
      }
      if (payload.type === "maverick.shell.sidebar.open" && isActiveWidgetCommand(event, widgetFrameRef.current, isActive)) {
        onOpenSidebar?.();
      }
      if (
        payload.type === "maverick.widget.primary-action.state" &&
        supportsPrimaryActionSlot &&
        isMountedWidgetFrameMessage(event, payload, widget, widgetFrameRef.current)
      ) {
        onPrimaryActionStateChange?.({
          available: payload.available === true,
          label: typeof payload.label === "string" ? payload.label : "",
          preferredSurface: payload.preferred_surface === "sidebar" ? "sidebar" : "app",
        });
      }
      if (
        payload.type === "maverick.app.external-url" &&
        isMountedWidgetFrameMessage(event, payload, widget, widgetFrameRef.current)
      ) {
        const url = externalHttpUrlFromMessage(payload.url);
        if (url) {
          openExternalUrl(url);
        }
        return;
      }
      if (
        payload.type === "maverick.shell.capture-area.start" &&
        size === "overlay" &&
        isMountedWidgetFrameMessage(event, payload, widget, widgetFrameRef.current)
      ) {
        const nextNavigationScope = typeof payload.navigation_scope === "string" ? payload.navigation_scope : "";
        captureNavigationScopeRef.current = nextNavigationScope;
        void startCaptureSession();
      }
      if (
        payload.type === "maverick.widget.resize" &&
        isMountedWidgetFrameMessage(event, payload, widget, widgetFrameRef.current)
      ) {
        if (size === "overlay") {
          const nextOverlaySize = overlayWidgetSizeFromMessage(payload);
          if (nextOverlaySize) {
            setOverlaySize(nextOverlaySize);
          }
          return;
        }
        if (size === "compact") {
          const nextCompactHeight = compactWidgetHeightFromMessage(payload);
          if (nextCompactHeight) {
            setCompactSlotHeight(nextCompactHeight);
          }
        }
      }
      if (
        payload.type === "maverick.chat.active-thread-changed"
        && widget
        && payload.owner_app_id === widget.owner_app_id
        && (senderIsShell || senderOwnerAppId === payload.owner_app_id)
      ) {
        const ownerAppId = widget.owner_app_id;
        const activeThreadId = typeof payload.active_thread_id === "string" ? payload.active_thread_id.trim() : "";
        const navigationScope = typeof payload.navigation_scope === "string" ? payload.navigation_scope.trim() : "";
        if (activeThreadId) {
          onActiveThreadChange?.({
            navigationScope,
            ownerAppId,
            threadId: activeThreadId,
          });
        }
        postToMaverickFrame(
          widgetFrameRef.current,
          {
            type: "maverick.chat.active-thread-changed",
            active_thread_id: activeThreadId,
            navigation_scope: navigationScope,
            owner_app_id: ownerAppId,
          },
        );
      }
      const selectionMessage = widgetSelectionChangedMessage(payload, widget?.owner_app_id);
      if (
        selectionMessage
        && payload.owner_app_id
        && (senderIsShell || senderOwnerAppId === payload.owner_app_id)
      ) {
        postToMaverickFrame(widgetFrameRef.current, selectionMessage);
      }
      if (
        payload.type === "maverick.app.data-changed"
        && typeof payload.owner_app_id === "string"
        && payload.owner_app_id === widget?.owner_app_id
        && (senderIsShell || senderOwnerAppId === payload.owner_app_id)
      ) {
        postToMaverickFrame(
          widgetFrameRef.current,
          {
            type: "maverick.widget.data-changed",
            active_thread_id: typeof payload.active_thread_id === "string" ? payload.active_thread_id : "",
            ...(payload.detail && typeof payload.detail === "object" ? { detail: payload.detail } : {}),
            navigation_scope: typeof payload.navigation_scope === "string" ? payload.navigation_scope : "",
            owner_app_id: payload.owner_app_id,
            resource: payload.resource || "",
          },
        );
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [
    frameScope,
    isActive,
    onCloseDock,
    onCloseSidebar,
    onActiveThreadChange,
    onOpenApp,
    onOpenDock,
    onOpenSidebar,
    onPrimaryActionStateChange,
    size,
    supportsPrimaryActionSlot,
    widget?.owner_app_id,
    widget?.widget_id,
  ]);

  useEffect(() => {
    if (primaryActionRequestId === lastPrimaryActionRequestRef.current) {
      return;
    }
    lastPrimaryActionRequestRef.current = primaryActionRequestId;
    if (!supportsPrimaryActionSlot || !widget) {
      return;
    }
    postToMaverickFrame(
      widgetFrameRef.current,
      {
        type: "maverick.widget.primary-action.invoke",
        owner_app_id: widget.owner_app_id,
        widget_id: widget.widget_id,
      },
    );
  }, [primaryActionRequestId, supportsPrimaryActionSlot, widget?.owner_app_id, widget?.widget_id]);

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

  const slotStyle =
    size === "overlay"
      ? overlaySize
      : size === "compact"
        ? { height: compactSlotHeight, maxHeight: compactSlotHeight, minHeight: compactSlotHeight }
        : undefined;
  const supportsShellPending = contentKind === "shell.sidebar.primary";

  if (!widget || !contextToken || (size === "overlay" && activeAppId && activeAppId === widget.owner_app_id)) {
    if (isResolvingWidget && supportsShellPending) {
      return <WidgetSlotPending label={label} size={size} style={slotStyle} />;
    }
    return error ? <p className="bs-widget-slot__fallback">{error}</p> : null;
  }

  const widgetFrameKey = `${frameScope.sessionGeneration}:${activeWorkspaceId}:${widget.owner_app_id}:${widget.widget_id}:${contextToken}:${frameRevision}`;
  const bootstrapTheme = bootstrapThemeForFrame(widgetFrameBootstrapThemesRef.current, widgetFrameKey, shellTheme);
  const src = widgetFrameSrc(widget.frontend_mount, contextToken, frameRevision, bootstrapTheme);
  const isWidgetFrameLoading = supportsShellPending && loadedFrameKey !== widgetFrameKey;
  const isCollapsedOverlay = size === "overlay" && overlaySize.width === COLLAPSED_OVERLAY_SIZE && overlaySize.height === COLLAPSED_OVERLAY_SIZE;
  const widgetAllowPolicy = widgetFrameBrowserFeaturePolicy(widget.owner_app_id);

  return (
    <>
      <section
        className={`bs-widget-slot bs-widget-slot--${size}${isCollapsedOverlay ? " is-collapsed" : ""}`}
        aria-label={label}
        style={slotStyle}
      >
        <IsolatedMaverickFrame
          allow={widgetAllowPolicy}
          allowFullScreen
          appId={widget.owner_app_id}
          frameScope={frameScope}
          className="bs-widget-slot__frame"
          key={widgetFrameKey}
          onLoad={() => {
            setLoadedFrameKey(widgetFrameKey);
            postMaverickShellTheme(widgetFrameRef.current, shellTheme);
            postWidgetContextChanged();
          }}
          ref={widgetFrameRef}
          sandbox={MAVERICK_IFRAME_SANDBOX}
          launchPath={src}
          title={label}
        />
        {isWidgetFrameLoading ? (
          <div className="bs-widget-slot__pending">
            <ShellPendingIndicator ariaLabel={`Loading ${label}`} label={pendingLabelForSlot(label, size)} size={size === "compact" ? "sm" : "md"} />
          </div>
        ) : null}
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

function WidgetSlotPending({
  label,
  size,
  style,
}: {
  label: string;
  size: "compact" | "fill" | "overlay";
  style?: { height?: string; maxHeight?: string; minHeight?: string; width?: string };
}) {
  return (
    <section className={`bs-widget-slot bs-widget-slot--${size} bs-widget-slot--pending`} aria-label={label} style={style}>
      <div className="bs-widget-slot__pending">
        <ShellPendingIndicator ariaLabel={`Loading ${label}`} label={pendingLabelForSlot(label, size)} size={size === "compact" ? "sm" : "md"} />
      </div>
    </section>
  );
}

function pendingLabelForSlot(label: string, size: "compact" | "fill" | "overlay"): string {
  return size === "compact" ? "Loading" : `Loading ${label}`;
}

function collapsedOverlaySize() {
  return { height: COLLAPSED_OVERLAY_SIZE, width: COLLAPSED_OVERLAY_SIZE };
}

function isMountedWidgetFrameMessage(
  event: MessageEvent,
  payload: WidgetMessagePayload,
  widget: WidgetRegistryItem | null,
  frame: HTMLIFrameElement | null,
): boolean {
  return (
    !!widget &&
    event.source === frame?.contentWindow &&
    payload.owner_app_id === widget.owner_app_id &&
    payload.widget_id === widget.widget_id
  );
}

function isMountedWidgetFrameSource(event: MessageEvent, frame: HTMLIFrameElement | null): boolean {
  return event.source === frame?.contentWindow;
}

function isActiveWidgetCommand(event: MessageEvent, frame: HTMLIFrameElement | null, isActive: boolean): boolean {
  return isMountedWidgetFrameSource(event, frame) || (isActive && event.source === window);
}

function overlayWidgetSizeFromMessage(payload: WidgetMessagePayload): { height: string; width: string } | null {
  const width = boundedPixelSize(payload.width, MAX_OVERLAY_WIDTH_PX);
  const height = boundedPixelSize(payload.height, MAX_OVERLAY_HEIGHT_PX);
  if (!width || !height) {
    return null;
  }
  return { height, width };
}

function compactWidgetHeightFromMessage(payload: WidgetMessagePayload): string | null {
  if (payload.height === COMPACT_SLOT_DEFAULT_HEIGHT) {
    return COMPACT_SLOT_DEFAULT_HEIGHT;
  }
  return boundedCompactSize(payload.height);
}

function boundedPixelSize(value: unknown, maxPx: number): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = value.trim().match(PIXEL_SIZE_PATTERN);
  if (!match) {
    return null;
  }
  const parsed = Number(match[1]);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > maxPx) {
    return null;
  }
  return `${Math.ceil(parsed)}px`;
}

function boundedCompactSize(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = value.trim().match(COMPACT_SIZE_PATTERN);
  if (!match) {
    return null;
  }
  const parsed = Number(match[1]);
  const unit = match[2];
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  if (unit === "px") {
    return parsed > MAX_COMPACT_SLOT_HEIGHT_PX ? null : `${Math.ceil(parsed)}px`;
  }
  return parsed > MAX_COMPACT_SLOT_HEIGHT_REM ? null : `${parsed}rem`;
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

function widgetFrameSrc(frontendMount: string, contextToken: string, revision: number, shellTheme: ShellThemeState): string {
  const url = urlWithShellThemeSearchParams(frontendMount, shellTheme);
  if (revision > 0) {
    url.searchParams.set("_maverick_refresh", String(revision));
  }
  url.hash = `context=${encodeURIComponent(contextToken)}`;
  return `${url.pathname}${url.search}${url.hash}`;
}

function themedWidgetContextContent({
  activeWorkspaceId,
  content,
  contentKind,
  shellTheme,
}: {
  activeWorkspaceId: string;
  content: Record<string, unknown>;
  contentKind: string;
  shellTheme: ShellThemeState;
}) {
  return {
    kind: contentKind,
    workspace_id: activeWorkspaceId,
    payload: content,
    shell_theme: shellTheme,
  };
}

function bootstrapThemeForFrame(
  themesByFrameKey: Record<string, ShellThemeState>,
  frameKey: string,
  shellTheme: ShellThemeState,
): ShellThemeState {
  themesByFrameKey[frameKey] = themesByFrameKey[frameKey] || shellTheme;
  return themesByFrameKey[frameKey];
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
