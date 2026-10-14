import { useCallback, useEffect, useRef, useState } from "react";
import { connectAppEventSocket } from "@loopino/pwa-cache";
import { callBackend } from "../api";
import { todayIso } from "../format";

export type SidebarSummary = {
  overdue_deliveries: number;
  approvals: number;
  open_tasks: number;
  receivables: number;
  overdue_payments: number;
};

export function useSidebarSummary(appId: string) {
  const [summary, setSummary] = useState<SidebarSummary | null>(null);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const day = useRef(todayIso());
  const refresh = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    day.current = todayIso();
    try {
      const payload = await callBackend<{ summary: SidebarSummary }>(
        {
          action: "sidebar_summary",
          today: day.current,
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setSummary(payload.summary);
        setError("");
      }
    } catch {
      if (!controller.signal.aborted) {
        setSummary(null);
        setError("Contatori non disponibili.");
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    const disconnect = connectAppEventSocket<{
      type?: string;
      owner_app_id?: string;
      resource?: string;
    }>(
      (message) => {
        if (
          message.type === "loopino.app.data-changed" &&
          message.owner_app_id === appId &&
          message.resource === "state"
        )
          void refresh();
      },
      () => {
        void refresh();
      },
    );
    function onVisibility() {
      if (document.visibilityState === "visible") void refresh();
    }
    document.addEventListener("visibilitychange", onVisibility);
    const timer = window.setInterval(() => {
      if (todayIso() !== day.current) void refresh();
    }, 60_000);
    return () => {
      disconnect();
      request.current?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [appId, refresh]);

  return { summary, error, refresh };
}
