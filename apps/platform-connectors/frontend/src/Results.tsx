import { useState } from "react";
import {
  shellHref,
  dateLabel,
  externalUrl,
  type Item,
  type Transcript,
} from "./api";

function TranscriptView({ transcript }: { transcript: Transcript }) {
  return (
    <div className="transcript">
      <div className="meta">
        Transcript · {transcript.language || "Language detected"} ·{" "}
        {transcript.engine || transcript.status}
        {transcript.automatic && " · Automatic captions"}
      </div>
      {transcript.segments?.length ? (
        <details>
          <summary>
            Read timed transcript ({transcript.segments.length} segments)
          </summary>
          <div className="segments">
            {transcript.segments.map((segment, index) => (
              <p key={index}>
                <time>
                  {Math.floor(segment.start / 60)}:
                  {String(Math.floor(segment.start % 60)).padStart(2, "0")}
                </time>
                {segment.text}
              </p>
            ))}
          </div>
        </details>
      ) : (
        <p className="source-text">
          {transcript.text ||
            `Transcription ${transcript.status || "unavailable"}.`}
        </p>
      )}
    </div>
  );
}

function ItemCard({ item, index }: { item: Item; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const transcript = item.transcript || item.media?.transcription;
  return (
    <article className="result-card">
      <div className="result-top">
        <span className="index">{String(index + 1).padStart(2, "0")}</span>
        <span className={"tag " + (item.content_observed ? "observed" : "")}>
          {item.content_observed ? "Read" : "Link found"}
        </span>
        <span className="meta">{dateLabel(item.observed_at)}</span>
      </div>
      <h3>
        <a href={externalUrl(item.url)} target="_blank" rel="noreferrer">
          {item.title || item.url || "Source observation"}{" "}
          <span aria-hidden>↗</span>
        </a>
      </h3>
      {item.author && <p className="meta">By {item.author}</p>}
      <p className={"source-text " + (!expanded ? "clamped" : "")}>
        {item.text ||
          (item.content_observed
            ? "No readable text in this observation."
            : "Open this source to read its content.")}
      </p>
      {(item.text?.length || 0) > 500 && (
        <button className="text-button" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show less" : "Read more"}
        </button>
      )}
      {item.truncated && (
        <p className="meta">This observation reached its text limit.</p>
      )}
      {!!item.images?.length && (
        <details>
          <summary>Image sources ({item.images.length})</summary>
          <div className="image-links">
            {item.images.slice(0, 24).map((image, i) => (
              <a
                key={i}
                href={externalUrl(image.url)}
                target="_blank"
                rel="noreferrer"
              >
                {image.alt || `Image ${i + 1}`} ↗
              </a>
            ))}
          </div>
        </details>
      )}
      {!!item.media?.frames?.length && (
        <div className="evidence">
          <div className="meta">
            Video evidence · {item.media.covered_seconds}s observed of{" "}
            {item.media.duration_seconds}s
          </div>
          <div className="frame-links">
            {item.media.frames.map((frame, i) =>
              frame.storage ? (
                <a
                  key={i}
                  href={shellHref(frame.storage.deep_link)}
                  target="_top"
                >
                  Frame {i + 1} · {frame.time_seconds.toFixed(1)}s ↗
                </a>
              ) : (
                <span key={i} className="meta">
                  Frame {i + 1}: evidence unavailable
                </span>
              ),
            )}
          </div>
        </div>
      )}
      {transcript && <TranscriptView transcript={transcript} />}
      <a
        className="source-link"
        href={externalUrl(item.url)}
        target="_blank"
        rel="noreferrer"
      >
        {item.url}
      </a>
    </article>
  );
}

export function Results({ items }: { items: Item[] }) {
  return (
    <div className="result-list">
      {items.map((item, index) => (
        <ItemCard item={item} index={index} key={item.url + "-" + index} />
      ))}
    </div>
  );
}
