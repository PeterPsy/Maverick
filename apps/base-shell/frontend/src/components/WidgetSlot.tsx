import { useEffect, useState } from "react";
import { createWidgetContext, listWidgets, WidgetRegistryItem } from "../api";

export function WidgetSlot({
  content,
  contentKind,
  hostAppId,
  label,
  onOpenApp,
}: {
  content: Record<string, unknown>;
  contentKind: string;
  hostAppId: string;
  label: string;
  onOpenApp: (appId: string, params?: Record<string, string | boolean | null>) => void;
}) {
  const [widget, setWidget] = useState<WidgetRegistryItem | null>(null);
  const [contextToken, setContextToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const contentSignature = JSON.stringify(content);

  useEffect(() => {
    let cancelled = false;

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
          message_id: `${hostAppId}:${contentKind}`,
          content: { kind: contentKind, payload: content },
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
  }, [contentSignature, contentKind, hostAppId]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as { type?: string; app_id?: string; params?: Record<string, string | boolean | null> };
      if (payload.type === "maverick.widget.open-app" && payload.app_id) {
        onOpenApp(payload.app_id, payload.params);
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [onOpenApp]);

  if (!widget || !contextToken) {
    return error ? <p className="bs-widget-slot__fallback">{error}</p> : null;
  }

  const src = `${widget.frontend_mount}?context=${encodeURIComponent(contextToken)}`;
  return (
    <section className="bs-widget-slot" aria-label={label}>
      <iframe className="bs-widget-slot__frame" src={src} title={label} />
    </section>
  );
}
