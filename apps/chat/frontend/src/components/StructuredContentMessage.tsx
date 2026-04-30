import { StructuredContent } from "../api/client";
import { WidgetHostFrame } from "./WidgetHostFrame";

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
      fallback={(state) => (
        <div className="chatapp-structured-card">
          <div className="chatapp-structured-card__header">
            <span className="chatapp-structured-card__eyebrow">Structured content</span>
            <strong>{content.kind}</strong>
          </div>
          {state.status === "loading" ? <p>Ricerca widget compatibile...</p> : null}
          {state.status === "fallback" && state.reason ? <p>{state.reason}</p> : null}
          <pre>{JSON.stringify(content.payload, null, 2)}</pre>
        </div>
      )}
    />
  );
}
