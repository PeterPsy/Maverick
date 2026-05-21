export function ChatTranscriptSkeleton({ label }: { label: string }) {
  return (
    <div className="chatapp-transcript-skeleton" role="status" aria-label={label}>
      <SkeletonBubble variant="human" lines={["wide", "medium"]} />
      <SkeletonBubble variant="agent" lines={["wide", "wide", "medium", "tiny"]} />
      <SkeletonBubble variant="agent" lines={["medium", "wide", "wide", "short"]} />
      <SkeletonBubble variant="agent" lines={["wide", "medium", "medium"]} />
      <SkeletonBubble variant="agent" lines={["medium", "wide", "short"]} />
      <SkeletonBubble variant="agent" lines={["wide", "short"]} />
    </div>
  );
}

function SkeletonBubble({ lines, variant }: { lines: Array<"wide" | "medium" | "short" | "tiny">; variant: "agent" | "human" }) {
  if (variant === "human") {
    return (
      <article className="chatapp-bubble is-human chatapp-transcript-skeleton__bubble chatapp-transcript-skeleton__bubble--human" aria-hidden="true">
        <div className="chatapp-human-message">
          {lines.map((line, index) => (
            <span className={`chatapp-transcript-skeleton__line chatapp-transcript-skeleton__line--${line}`} key={`${line}-${index}`} />
          ))}
        </div>
      </article>
    );
  }

  return (
    <article className="chatapp-bubble is-agent chatapp-transcript-skeleton__bubble chatapp-transcript-skeleton__bubble--agent" aria-hidden="true">
      <div className="chatapp-agent-trace">
        <section className="chatapp-agent-block chatapp-agent-block--action">
          <div className="chatapp-agent-block__body">
            {lines.map((line, index) => (
              <span className={`chatapp-transcript-skeleton__line chatapp-transcript-skeleton__line--${line}`} key={`${line}-${index}`} />
            ))}
          </div>
        </section>
      </div>
    </article>
  );
}
