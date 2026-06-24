import { KeyboardEvent, useEffect, useRef } from "react";
import type { Ref } from "react";
import type { MentionItem } from "../lib/mentions";

export function MentionPanel({
  activeIndex,
  className = "",
  items,
  kind,
  onSelect,
  onSearchKeyDown,
  onSearchQueryChange,
  query,
  ref,
  searchInputRef,
  isLoading = false,
  searchPlaceholder,
  searchQuery,
  showHeader = true,
  showSearchLabel = true,
  statusMessage,
}: {
  activeIndex: number;
  className?: string;
  items: MentionItem[];
  kind: "app" | "skill";
  onSelect: (item: MentionItem) => void;
  onSearchKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  onSearchQueryChange?: (query: string) => void;
  query: string;
  ref?: Ref<HTMLDivElement>;
  searchInputRef?: Ref<HTMLInputElement>;
  isLoading?: boolean;
  searchPlaceholder?: string;
  searchQuery?: string;
  showHeader?: boolean;
  showSearchLabel?: boolean;
  statusMessage?: string | null;
}) {
  const activeItemRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const panelLabel = kind === "app" ? "App and reference suggestions" : "Skill suggestions";
  const panelTitle = kind === "app" ? "Apps and references" : "Skills";

  return (
    <div className={`chatapp-mention-panel ${className}`} ref={ref} role="listbox" aria-label={panelLabel}>
      {showHeader ? <div className="chatapp-mention-panel__header">{panelTitle}</div> : null}
      {onSearchQueryChange ? (
        <label className="chatapp-mention-panel__search">
          {showSearchLabel ? <span className="chatapp-mention-panel__search-label">Search</span> : null}
          <input
            aria-label="Search apps and references"
            className="chatapp-mention-panel__search-input"
            onChange={(event) => onSearchQueryChange(event.currentTarget.value)}
            onKeyDown={onSearchKeyDown}
            placeholder={searchPlaceholder || "Search"}
            ref={searchInputRef}
            type="search"
            value={searchQuery || ""}
          />
        </label>
      ) : null}
      {statusMessage ? (
        <div className="chatapp-mention-panel__error" role="status">
          {statusMessage}
        </div>
      ) : null}
      {items.length ? (
        items.map((item, index) => (
          <button
            aria-selected={index === activeIndex}
            className={`chatapp-mention-panel__item ${index === activeIndex ? "is-active" : ""}`}
            key={`${item.kind}:${item.id}`}
            onPointerDown={(event) => {
              event.preventDefault();
              onSelect(item);
            }}
            ref={index === activeIndex ? activeItemRef : null}
            role="option"
            type="button"
          >
            <span className="chatapp-mention-panel__name">
              {item.kind === "skill" ? "$" : "@"}
              {item.label}
            </span>
            {item.description ? <span className="chatapp-mention-panel__description">{item.description}</span> : null}
          </button>
        ))
      ) : statusMessage || isLoading ? null : (
        <div className="chatapp-mention-panel__empty">No results for {query.trim() || "this reference"}</div>
      )}
      {isLoading ? <MentionPanelSkeleton /> : null}
    </div>
  );
}

function MentionPanelSkeleton() {
  return (
    <div aria-label="Searching references" className="chatapp-mention-panel__skeleton" role="status">
      <div className="chatapp-mention-panel__skeleton-row">
        <span className="chatapp-mention-panel__skeleton-line chatapp-mention-panel__skeleton-line--title" />
        <span className="chatapp-mention-panel__skeleton-line chatapp-mention-panel__skeleton-line--detail" />
      </div>
    </div>
  );
}
