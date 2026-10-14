import { useEffect, useMemo, useRef, useState } from "react";
import {
  connectAppEventSocket,
  loopinoAppIsVisible,
  observeLoopinoVisibility,
} from "@loopino/pwa-cache";
import type { AppRegistryItem } from "../api";
import type { LoopinoFrameScope } from "../iframePolicy";
import {
  noticeKey,
  request,
  validNotice,
  type Inbox,
  type Notice,
} from "../notificationInbox";

/** One registry-driven reader; app providers own persistence, receipts and domain actions. */
export function useNotificationInbox(
  apps: AppRegistryItem[],
  scope: LoopinoFrameScope,
) {
  const providers = useMemo(
    () =>
      apps.filter(
        (app) =>
          app.status === "enabled" &&
          app.provides.some(
            (entry) =>
              entry.interface === "notifications.inbox" &&
              entry.version === "1" &&
              entry.surfaces.includes("backend"),
          ),
      ),
    [apps],
  );
  const [inboxes, setInboxes] = useState<Inbox[]>([]),
    [loadError, setLoadError] = useState(""),
    [error, setError] = useState("");
  const providerIds = useMemo(
    () => new Set(providers.map((app) => app.app_id)),
    [providers],
  );
  const [pages, setPages] = useState(1),
    [refresh, setRefresh] = useState(0),
    [pending, setPending] = useState<string[]>([]);
  const pendingRef = useRef(new Set<string>()),
    activeRef = useRef(true);
  const mutationRevision = useRef(0);
  useEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
    };
  }, []);
  useEffect(() => {
    let disposed = false,
      timer = 0;
    let controller: AbortController | undefined;
    const suspend = () => {
      window.clearTimeout(timer);
      controller?.abort();
    };
    const schedule = () => {
      window.clearTimeout(timer);
      if (!loopinoAppIsVisible()) return;
      timer = window.setTimeout(async () => {
        if (pendingRef.current.size) return;
        const revision = mutationRevision.current;
        controller?.abort();
        const current = new AbortController();
        controller = current;
        const results = await Promise.allSettled(
          providers.map(async (app) => {
            const value = await request(
              app.app_id,
              { action: "notifications.list", limit: 100 },
              current.signal,
            );
            if (
              !Array.isArray(value.notifications) ||
              !Number.isInteger(value.total) ||
              value.total < 0
            )
              throw new Error("Risposta notifiche non valida.");
            for (
              let offset = 100;
              offset < Math.min(value.total, pages * 100);
              offset += 100
            ) {
              const page = await request(
                app.app_id,
                { action: "notifications.list", limit: 100, offset },
                current.signal,
              );
              if (!Array.isArray(page.notifications))
                throw new Error("Risposta notifiche non valida.");
              value.notifications.push(...page.notifications);
            }
            const notices = [
              ...new Map<string, Notice>(
                value.notifications
                  .filter(validNotice)
                  .map((n: Notice) => [n.id, n] as const),
              ).values(),
            ];
            return {
              appId: app.app_id,
              name: app.name,
              logo: app.logo ?? null,
              notices,
              total: value.total,
              unread:
                Number.isInteger(value.unread_total) && value.unread_total >= 0
                  ? value.unread_total
                  : Math.max(
                      0,
                      value.total -
                        notices.filter((n) => n.read === true).length,
                    ),
              capabilities: {
                read: value.capabilities?.read === true,
                actions: value.capabilities?.actions === true,
              },
            };
          }),
        );
        if (
          disposed ||
          current.signal.aborted ||
          !loopinoAppIsVisible() ||
          pendingRef.current.size ||
          revision !== mutationRevision.current
        )
          return;
        setInboxes((previous) =>
          results.flatMap((result, i) =>
            result.status === "fulfilled"
              ? [result.value]
              : previous.filter((inbox) => inbox.appId === providers[i].app_id),
          ),
        );
        setLoadError(
          results.some((result) => result.status === "rejected")
            ? "Impossibile aggiornare le notifiche. Riprova."
            : "",
        );
      }, 100);
    };
    const stopVisibility = observeLoopinoVisibility((visible) =>
      visible ? schedule() : suspend(),
    );
    const stopEvents = connectAppEventSocket<{
      type?: string;
      owner_app_id?: string;
      resource?: string;
      workspace_id?: string;
    }>((event) => {
      if (
        event.type === "loopino.app.data-changed" &&
        event.resource === "notifications" &&
        (!event.workspace_id || event.workspace_id === scope.workspaceId) &&
        providers.some((app) => app.app_id === event.owner_app_id)
      )
        schedule();
    }, schedule);
    schedule();
    return () => {
      disposed = true;
      suspend();
      stopVisibility();
      stopEvents();
    };
  }, [providers, scope, refresh, pages]);

  async function mutate(
    inbox: Inbox,
    id: string | null,
    action: "dismiss" | "read" | "action",
    actionId?: string,
  ) {
    const key = noticeKey(inbox.appId, id);
    if (pendingRef.current.has(key)) return;
    mutationRevision.current += 1;
    pendingRef.current.add(key);
    setPending([...pendingRef.current]);
    try {
      const result = await request(inbox.appId, {
        action: `notifications.${action}`,
        ...(action === "read" && id === null ? { all: true } : { id }),
        ...(actionId ? { action_id: actionId } : {}),
      });
      if (!activeRef.current) return;
      setInboxes((current) =>
        current.map((value) => {
          if (value.appId !== inbox.appId) return value;
          if (action === "dismiss") {
            const notice = value.notices.find((n) => n.id === id);
            return {
              ...value,
              total: Math.max(0, value.total - (notice ? 1 : 0)),
              unread: Math.max(
                0,
                value.unread - (notice && !notice.read ? 1 : 0),
              ),
              notices: value.notices.filter((n) => n.id !== id),
            };
          }
          if (action === "read") {
            const unread =
              id === null
                ? 0
                : Math.max(
                    0,
                    value.unread -
                      (value.notices.some((n) => n.id === id && !n.read)
                        ? 1
                        : 0),
                  );
            return {
              ...value,
              unread,
              notices: value.notices.map((n) =>
                id === null || n.id === id ? { ...n, read: true } : n,
              ),
            };
          }
          if (validNotice(result.notification) && result.notification.id === id)
            return {
              ...value,
              notices: value.notices.map((n) =>
                n.id === id ? result.notification : n,
              ),
            };
          return value;
        }),
      );
      setError("");
    } catch (failure) {
      if (activeRef.current)
        setError(
          failure instanceof Error
            ? failure.message
            : "Impossibile salvare la notifica.",
        );
      throw failure;
    } finally {
      pendingRef.current.delete(key);
      if (activeRef.current) {
        setPending([...pendingRef.current]);
        if (!pendingRef.current.size) setRefresh((value) => value + 1);
      }
    }
  }
  async function readAll() {
    const results = await Promise.allSettled(
      inboxes
        .filter(
          (inbox) =>
            providerIds.has(inbox.appId) &&
            inbox.capabilities.read &&
            inbox.unread > 0,
        )
        .map((inbox) => mutate(inbox, null, "read")),
    );
    if (results.some((result) => result.status === "rejected"))
      setError("Alcune notifiche non sono state segnate come lette. Riprova.");
  }
  async function dismissMany(notices: { inbox: Inbox; notice: Notice }[]) {
    const results = await Promise.allSettled(
      notices.map(({ inbox, notice }) => mutate(inbox, notice.id, "dismiss")),
    );
    if (results.some((result) => result.status === "rejected"))
      setError("Alcune notifiche non sono state chiuse. Riprova.");
  }
  return {
    inboxes: inboxes.filter((inbox) => providerIds.has(inbox.appId)),
    error: error || loadError,
    pending,
    mutate,
    readAll,
    dismissMany,
    retry: () => {
      setError("");
      setRefresh((value) => value + 1);
    },
    loadMore: () => setPages((value) => value + 1),
  };
}
