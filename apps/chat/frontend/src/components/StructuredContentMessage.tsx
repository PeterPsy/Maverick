import type { StructuredContent } from "../api/client";
import { WidgetHostFrame } from "./WidgetHostFrame";
import { MorphingSpinner } from "./ui/morphing-spinner";

export function StructuredContentMessage({
  content,
  messageId,
}: {
  content: StructuredContent;
  messageId: string;
}) {
  return (
    <WidgetHostFrame
      content={content}
      hostAppId="chat"
      messageId={messageId}
      title={`${content.kind} widget`}
      fallback={(state) => {
        if (state.status === "loading") {
          return (
            <div className="chatapp-structured-widget-loader" role="status" aria-live="polite">
              <MorphingSpinner size="sm" />
              <span>Caricamento widget…</span>
            </div>
          );
        }
        return (
          <div className="chatapp-structured-card">
            <div className="chatapp-structured-card__header">
              <span className="chatapp-structured-card__eyebrow">Structured content</span>
              <strong>{content.kind}</strong>
            </div>
            {state.reason ? <p>{state.reason}</p> : null}
            <pre>{JSON.stringify(content.payload, null, 2)}</pre>
          </div>
        );
      }}
    />
  );
}
