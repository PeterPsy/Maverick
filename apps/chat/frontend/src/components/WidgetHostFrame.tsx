import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createWidgetContext, listWidgets } from "../api/client";
import type { StructuredContent, WidgetRegistryItem } from "../api/client";

type WidgetHostState =
  | { status: "loading" }
  | { status: "fallback"; reason?: string }
  | { status: "ready"; widget: WidgetRegistryItem; contextToken: string };

export function WidgetHostFrame({
  content,
  fallback,
  hostAppId,
  messageId,
  title,
}: {
  content: StructuredContent;
  fallback: (state: Extract<WidgetHostState, { status: "loading" | "fallback" }>) => ReactNode;
  hostAppId: string;
  messageId: string;
  title?: string;
}) {
  const [state, setState] = useState<WidgetHostState>({ status: "loading" });
  const [frameHeight, setFrameHeight] = useState<string | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const contentSignature = useMemo(() => stableContentSignature(content), [content]);

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
        if (!cancelled) {
          setState({ status: "ready", widget, contextToken: context.context_token });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ status: "fallback", reason: error instanceof Error ? error.message : "Widget unavailable." });
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
    if (state.status !== "ready") {
      return;
    }

    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { type?: string; height?: string };
      if (payload.type !== "maverick.widget.resize" || typeof payload.height !== "string" || !payload.height) {
        return;
      }
      setFrameHeight(payload.height);
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [state]);

  if (state.status === "ready") {
    const src = `${state.widget.frontend_mount}#context=${encodeURIComponent(state.contextToken)}`;
    return (
      <iframe
        className="chatapp-structured-widget"
        ref={frameRef}
        key={`${hostAppId}:${messageId}:${state.widget.owner_app_id}:${state.widget.widget_id}:${state.contextToken}`}
        src={src}
        style={frameHeight ? { height: frameHeight } : undefined}
        title={title || `${content.kind} widget`}
      />
    );
  }

  return <>{fallback(state)}</>;
}

function widgetContextTokenFromLocation(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  const hashToken = new URLSearchParams(hash).get("context");
  if (hashToken) {
    return hashToken;
  }
  return new URLSearchParams(window.location.search).get("context") || "";
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
