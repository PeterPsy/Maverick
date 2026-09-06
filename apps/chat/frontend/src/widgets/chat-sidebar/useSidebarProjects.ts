import { readAppCachePages } from "@maverick/pwa-cache";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatProject } from "../../api/client";
import { readChatDisplay } from "../../pwaCache";

type ProjectPage = { projects: ChatProject[]; has_more: boolean };

/** Project display reads have their own failure/recovery lifecycle, not the thread stream's. */
export function useSidebarProjects() {
  const [projects, setProjects] = useState<ChatProject[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const readRef = useRef<AbortController | null>(null);
  const failedRef = useRef(false);
  const pendingRef = useRef(false);

  const refresh = useCallback(async () => {
    readRef.current?.abort();
    const controller = new AbortController();
    readRef.current = controller;
    pendingRef.current = true;
    setIsLoading(true);
    const reportError = (loadError: unknown) => {
      if (controller.signal.aborted) return;
      failedRef.current = true;
      setError(loadError instanceof Error ? loadError.message : "Unable to load project names.");
    };
    try {
      await readAppCachePages<ProjectPage>({
        signal: controller.signal,
        pageSize: 200,
        hasMore: (page) => page.has_more,
        onUpdate: (pages) => {
          if (controller.signal.aborted) return;
          setProjects(pages.flatMap((page) => page.projects));
          failedRef.current = false;
          setError(null);
        },
        onError: reportError,
        readPage: (offset, onRevalidated) => readChatDisplay<ProjectPage>({ kind: "projects", offset }, {
          signal: controller.signal, onRevalidated, onRevalidationError: reportError,
        }),
      });
    } catch (loadError) {
      reportError(loadError);
    } finally {
      if (!controller.signal.aborted) {
        pendingRef.current = false;
        setIsLoading(false);
      }
    }
  }, []);

  const replaceProjects = useCallback((next: ChatProject[]) => {
    // A successful project mutation/read receipt supersedes any older display read.
    readRef.current?.abort();
    failedRef.current = false;
    pendingRef.current = false;
    setProjects(next);
    setError(null);
    setIsLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const recoverFailedRead = () => {
      if (!document.hidden && failedRef.current && !pendingRef.current) void refresh();
    };
    // No polling or custom HTTP replay: the approved SDK read owns transport retries.
    window.addEventListener("online", recoverFailedRead);
    window.addEventListener("focus", recoverFailedRead);
    document.addEventListener("visibilitychange", recoverFailedRead);
    return () => {
      readRef.current?.abort();
      window.removeEventListener("online", recoverFailedRead);
      window.removeEventListener("focus", recoverFailedRead);
      document.removeEventListener("visibilitychange", recoverFailedRead);
    };
  }, [refresh]);

  return { projects, error, isLoading, refresh, replaceProjects };
}
