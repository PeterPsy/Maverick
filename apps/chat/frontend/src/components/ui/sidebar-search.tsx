import { useEffect, useRef } from "react";
import { Search, X } from "lucide-react";

export function SidebarSearch({
  expanded,
  onExpandedChange,
  onSearchChange,
  searchQuery,
  label = "Search chats",
  placeholder = "Search chats and messages",
  enableShortcut = true,
}: {
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  onSearchChange: (query: string) => void;
  searchQuery: string;
  label?: string;
  placeholder?: string;
  enableShortcut?: boolean;
}) {
  const searchRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef(false);

  useEffect(() => {
    if (expanded) {
      searchRef.current?.focus();
      searchRef.current?.select();
    } else if (restoreFocusRef.current) {
      restoreFocusRef.current = false;
      triggerRef.current?.focus();
    }
  }, [expanded]);

  useEffect(() => {
    if (!enableShortcut) return;
    function focusSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onExpandedChange(true);
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    }
    document.addEventListener("keydown", focusSearch);
    return () => document.removeEventListener("keydown", focusSearch);
  }, [enableShortcut, onExpandedChange]);

  function closeSearch() {
    restoreFocusRef.current = true;
    onExpandedChange(false);
  }

  if (!expanded) {
    return (
      <button
        aria-label={label}
        className={`dashboard-sidebar__search-trigger ${searchQuery ? "has-query" : ""}`}
        onClick={() => onExpandedChange(true)}
        ref={triggerRef}
        title={
          searchQuery
            ? `Search: ${searchQuery}`
            : `${placeholder}${enableShortcut ? " (⌘/Ctrl K)" : ""}`
        }
        type="button"
      >
        <Search aria-hidden="true" size={17} />
        {searchQuery ? (
          <span
            aria-hidden="true"
            className="dashboard-sidebar__search-indicator"
          />
        ) : null}
      </button>
    );
  }

  return (
    <div
      className="bs-chat-sidebar-search-frame"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          onExpandedChange(false);
      }}
    >
      <Search aria-hidden="true" size={16} />
      <input
        aria-label={label}
        className="bs-chat-sidebar-search"
        onChange={(event) => onSearchChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onSearchChange("");
            closeSearch();
          }
        }}
        placeholder={placeholder}
        ref={searchRef}
        value={searchQuery}
      />
      <button
        aria-label={searchQuery ? `Clear ${label.toLowerCase()}` : `Close ${label.toLowerCase()}`}
        className="dashboard-sidebar__icon-button"
        onClick={() => {
          if (searchQuery) {
            onSearchChange("");
            searchRef.current?.focus();
          } else closeSearch();
        }}
        type="button"
      >
        <X aria-hidden="true" size={14} />
      </button>
    </div>
  );
}
