import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createWidgetContext, listWidgets } from "../api/client";
import type { StructuredContent, WidgetRegistryItem } from "../api/client";
import {
  isNestedWidgetLoadedMessage,
  NESTED_WIDGET_LOAD_TIMEOUT_MS,
  requestNestedWidgetLaunch,
  submitNestedWidgetBootstrap,
} from "../lib/nestedWidgetFrame";
import type { NestedWidgetLaunch } from "../lib/nestedWidgetFrame";
import { openAppParamsInShell } from "../lib/shellNavigation";
import { boundedWidgetHeightPx } from "../lib/widgetResize";

const MAVERICK_WIDGET_IFRAME_SANDBOX = "allow-downloads allow-forms allow-popups allow-same-origin allow-scripts";

type MountedWidgetState = {
  contextToken: string;
  launch: NestedWidgetLaunch;
  widget: WidgetRegistryItem;
};

type WidgetHostState =
  | { status: "loading" }
  | { status: "fallback"; reason?: string }
  | ({ status: "launching" | "ready" } & MountedWidgetState);

type WidgetFallbackState = Extract<WidgetHostState, { status: "loading" | "fallback" }>;

export function WidgetHostFrame({
  content,
  fallback,
  hostAppId,
  messageId,
  title,
}: {
  content: StructuredContent;
  fallback: (state: WidgetFallbackState) => ReactNode;
  hostAppId: string;
  messageId: string;
  title?: string;
}) {
  const [state, setState] = useState<WidgetHostState>({ status: "loading" });
  const [frameHeight, setFrameHeight] = useState<number | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const submittedTicketRef = useRef("");
  const contentSignature = useMemo(() => stableContentSignature(content), [content]);
  const frameName = useMemo(
    () => `maverick-widget-${Math.random().toString(36).slice(2)}`,
    [contentSignature, hostAppId, messageId],
  );

  useEffect(() => {
    let cancelled = false;
    setFrameHeight(null);

    async function loadWidget() {
      try {
        const registry = await listWidgets(hostAppId, content.kind);
        const widget = registry.items[0];
        if (!widget) {
          if (!cancelled) {
            setState({ status: "fallback" });
          }
          return;
        }
        const context = await createWidgetContext({
          host_app_id: hostAppId,
          owner_app_id: widget.owner_app_id,
          widget_id: widget.widget_id,
          message_id: messageId,
          content,
        });
        const launch = await requestNestedWidgetLaunch(widget, context.context_token);
        if (!cancelled) {
          setState({
            status: "launching",
            widget,
            contextToken: context.context_token,
            launch,
          });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ status: "fallback", reason: widgetErrorMessage(error) });
        }
      }
    }

    setState({ status: "loading" });
    void loadWidget();
    return () => {
      cancelled = true;
    };
  }, [contentSignature, hostAppId, messageId]);

  useEffect(() => {
    if (state.status !== "launching" && state.status !== "ready") {
      return;
    }
    const { launch, widget } = state;

    function handleMessage(event: MessageEvent) {
      if (isNestedWidgetLoadedMessage(event, frameRef.current, launch)) {
        setState((current) => (
          current.status === "launching" && current.launch.ticket === launch.ticket
            ? { ...current, status: "ready" }
            : current
        ));
        return;
      }
      if (
        event.origin !== launch.origin
        || event.source !== frameRef.current?.contentWindow
        || !event.data
        || typeof event.data !== "object"
      ) {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        height?: string;
        owner_app_id?: string;
        params?: unknown;
        type?: string;
        widget_id?: string;
      };
      if (payload.type === "maverick.app-frame.authorization-required") {
        setState({ status: "fallback", reason: "Widget session unavailable." });
        return;
      }
      if (state.status !== "ready") {
        return;
      }
      if (
        payload.type === "maverick.widget.resize"
        && payload.owner_app_id === widget.owner_app_id
        && payload.widget_id === widget.widget_id
      ) {
        const nextHeight = boundedWidgetHeightPx(payload.height);
        if (nextHeight !== null) {
          setFrameHeight(nextHeight);
        }
        return;
      }
      if (payload.type === "maverick.widget.open-app" && typeof payload.app_id === "string") {
        openAppParamsInShell(payload.app_id, shellRouteParamsFromWidgetParams(payload.params));
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [state]);

  useEffect(() => {
    if (state.status !== "launching") {
      return;
    }
    let active = true;
    const frame = frameRef.current;
    if (!frame) {
      setState({ status: "fallback", reason: "Widget frame unavailable." });
      return;
    }
    try {
      if (submittedTicketRef.current !== state.launch.ticket) {
        submittedTicketRef.current = state.launch.ticket;
        void submitNestedWidgetBootstrap(frame, state.launch).catch((error: unknown) => {
          if (active) {
            setState((current) => (
              current.status === "launching" && current.launch.ticket === state.launch.ticket
                ? { status: "fallback", reason: widgetErrorMessage(error) }
                : current
            ));
          }
        });
      }
    } catch (error) {
      setState({ status: "fallback", reason: widgetErrorMessage(error) });
      return;
    }
    const timeout = window.setTimeout(() => {
      setState((current) => (
        current.status === "launching" && current.launch.ticket === state.launch.ticket
          ? { status: "fallback", reason: "Widget load timed out." }
          : current
      ));
    }, NESTED_WIDGET_LOAD_TIMEOUT_MS);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [state]);

  if (state.status === "loading" || state.status === "fallback") {
    return <>{fallback(state)}</>;
  }

  const loading = state.status === "launching";
  return (
    <>
      {loading ? fallback({ status: "loading" }) : null}
      <iframe
        allow="fullscreen"
        allowFullScreen
        aria-hidden={loading}
        className="chatapp-structured-widget"
        hidden={loading}
        key={`${hostAppId}:${messageId}:${state.widget.owner_app_id}:${state.widget.widget_id}:${state.contextToken}`}
        name={frameName}
        onError={() => setState({ status: "fallback", reason: "Widget frame failed to load." })}
        ref={frameRef}
        sandbox={MAVERICK_WIDGET_IFRAME_SANDBOX}
        scrolling="no"
        src="about:blank"
        style={frameHeight ? { height: `${frameHeight}px` } : undefined}
        title={title || `${content.kind} widget`}
      />
    </>
  );
}

function widgetErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "Widget unavailable.";
}

function shellRouteParamsFromWidgetParams(params: unknown): Record<string, string | boolean | null> {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    return {};
  }
  const routeParams: Record<string, string | boolean | null> = {};
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === "string" || typeof value === "boolean" || value === null) {
      routeParams[key] = value;
    }
  }
  return routeParams;
}

function stableContentSignature(content: StructuredContent): string {
  return `${content.kind}:${stableJson(content.payload)}`;
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}
