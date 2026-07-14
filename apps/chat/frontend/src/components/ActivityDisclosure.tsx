import { useEffect, useId, useState, type ReactNode } from "react";

type ActivityDisclosureProps = {
  children: ReactNode;
  createdAt?: string;
  defaultExpanded?: boolean;
  label: string;
};

export function ActivityDisclosure({ children, createdAt, defaultExpanded = false, label }: ActivityDisclosureProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const disclosureId = useId();
  const timestamp = formatActivityTime(createdAt);

  useEffect(() => {
    setIsExpanded(defaultExpanded);
  }, [defaultExpanded]);

  return (
    <div className="chatapp-tool-inline">
      <button
        aria-controls={disclosureId}
        aria-expanded={isExpanded}
        className="chatapp-tool-inline__toggle"
        onClick={() => setIsExpanded((current) => !current)}
        type="button"
      >
        <span className={`chatapp-tool-inline__chevron ${isExpanded ? "is-expanded" : ""}`} aria-hidden="true">
          <span className="material-symbols-rounded">expand_more</span>
        </span>
        <span className="chatapp-tool-inline__toggle-label">{label}</span>
        {timestamp ? (
          <time className="chatapp-tool-inline__time" dateTime={createdAt}>
            {timestamp}
          </time>
        ) : null}
      </button>
      <div
        aria-hidden={!isExpanded}
        className={`chatapp-tool-inline__body ${isExpanded ? "" : "is-collapsed"}`}
        id={disclosureId}
      >
        <div className="chatapp-tool-inline__body-inner">{children}</div>
      </div>
    </div>
  );
}

function formatActivityTime(value?: string): string {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}
