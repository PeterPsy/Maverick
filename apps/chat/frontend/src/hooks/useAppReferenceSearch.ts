import { type Dispatch, type SetStateAction, useEffect } from "react";
import type { MentionItem } from "../lib/mentions";

const REFERENCE_SEARCH_ERROR_MESSAGE = "Unable to search apps or records. Try again or reload the page.";

export function useAppReferenceSearch({
  isOpen,
  onSearchReferences,
  query,
  setError,
  setItems,
  setPending,
}: {
  isOpen: boolean;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  query: string;
  setError: Dispatch<SetStateAction<string | null>>;
  setItems: Dispatch<SetStateAction<MentionItem[]>>;
  setPending: Dispatch<SetStateAction<boolean>>;
}) {
  useEffect(() => {
    if (!isOpen || !onSearchReferences) {
      setPending(false);
      if (!isOpen) {
        setError(null);
      }
      return;
    }
    const trimmedQuery = query.trim();
    setError(null);
    setItems([]);
    setPending(true);
    const controller = new AbortController();
    let disposed = false;
    const timer = window.setTimeout(() => {
      onSearchReferences(trimmedQuery, controller.signal)
        .then((nextItems) => {
          if (disposed) {
            return;
          }
          setItems(nextItems);
          setError(null);
        })
        .catch((searchError) => {
          if (disposed || isAbortError(searchError)) {
            return;
          }
          setItems([]);
          setError(REFERENCE_SEARCH_ERROR_MESSAGE);
        })
        .finally(() => {
          if (!disposed) {
            setPending(false);
          }
        });
    }, 160);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [isOpen, onSearchReferences, query, setError, setItems, setPending]);
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "name" in error && error.name === "AbortError");
}
