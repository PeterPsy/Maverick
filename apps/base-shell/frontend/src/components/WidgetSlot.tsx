import { useEffect, useRef, useState } from "react";
import { createWidgetContext, listWidgets, WidgetRegistryItem } from "../api";

export function WidgetSlot({
  activeWorkspaceId,
  content,
  contentKind,
  hostAppId,
  label,
  onOpenApp,
  size = "fill",
}: {
  activeWorkspaceId: string;
  content: Record<string, unknown>;
  contentKind: string;
  hostAppId: string;
  label: string;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
  size?: "compact" | "fill";
}) {
  const [widget, setWidget] = useState<WidgetRegistryItem | null>(null);
  const [contextToken, setContextToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const widgetFrameRef = useRef<HTMLIFrameElement | null>(null);
  const contentSignature = JSON.stringify({ activeWorkspaceId, content });

  useEffect(() => {
    let cancelled = false;
    setWidget(null);
    setContextToken(null);
    setError(null);

    async function loadWidget() {
      try {
        const registry = await listWidgets(hostAppId, contentKind);
        const selected = registry.items[0] || null;
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
  }, [activeWorkspaceId, contentSignature, contentKind, hostAppId]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
      };
      if (payload.type === "maverick.widget.open-app" && payload.app_id) {
        onOpenApp(payload.app_id, payload.params);
      }
      if (payload.type === "maverick.app.data-changed" && payload.owner_app_id === widget?.owner_app_id) {
        widgetFrameRef.current?.contentWindow?.postMessage(
          {
            type: "maverick.widget.data-changed",
            owner_app_id: payload.owner_app_id,
            resource: payload.resource || "",
          },
          window.location.origin,
        );
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onOpenApp, widget?.owner_app_id]);

  if (!widget || !contextToken) {
    return error ? <p className="bs-widget-slot__fallback">{error}</p> : null;
  }

  const src = `${widget.frontend_mount}?context=${encodeURIComponent(contextToken)}`;
  return (
    <section className={`bs-widget-slot bs-widget-slot--${size}`} aria-label={label}>
      <iframe
        className="bs-widget-slot__frame"
        key={`${activeWorkspaceId}:${widget.owner_app_id}:${widget.widget_id}:${contextToken}`}
        ref={widgetFrameRef}
        src={src}
        title={label}
      />
    </section>
  );
}
