import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NotificationPopover } from "./NotificationPopover";
import {
  connectAppEventSocket,
  maverickAppIsVisible,
  observeMaverickVisibility,
} from "@maverick/pwa-cache";
import type { AppRegistryItem } from "../api";
import type { MaverickFrameScope } from "../iframePolicy";
import {
  request,
  noticeTime,
  type Notice,
  type Inbox,
} from "../notificationInbox";

/** App-owned inboxes remain available while any authenticated app is active. */
export function AppNotifications({
  apps,
  scope,
  onOpenApp,
  children,
  placement,
}: {
  apps: AppRegistryItem[];
  scope: MaverickFrameScope;
  children: (notifications: ReactNode) => ReactNode;
  placement: "sidebar" | "header";
  onOpenApp: (
    appId: string,
    params?: Record<string, string | boolean | null>,
  ) => void;
}) {
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
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(5);
  const [pages, setPages] = useState(1);
  const [pending, setPending] = useState<string[]>([]);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let disposed = false;
    let timer = 0;
    let controller: AbortController | undefined;
    const suspend = () => {
      window.clearTimeout(timer);
      controller?.abort();
    };
    const schedule = () => {
      window.clearTimeout(timer);
      if (!maverickAppIsVisible()) return;
      timer = window.setTimeout(async () => {
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
              !Number.isInteger(value.total)
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
            return {
              appId: app.app_id,
              name: app.name,
              notices: value.notifications.filter(
                (n: Notice) =>
                  typeof n.id === "string" && typeof n.title === "string",
              ),
              total: value.total,
            };
          }),
        );
        if (disposed || current.signal.aborted || !maverickAppIsVisible())
          return;
        setInboxes((previous) =>
          results.flatMap((result, i) =>
            result.status === "fulfilled"
              ? [result.value]
              : previous.filter((inbox) => inbox.appId === providers[i].app_id),
          ),
        );
        setError(
          results.some((result) => result.status === "rejected")
            ? "Impossibile aggiornare le notifiche. Riprova."
            : "",
        );
      }, 100);
    };
    const stopVisibility = observeMaverickVisibility((visible) =>
      visible ? schedule() : suspend(),
    );
    const stopEvents = connectAppEventSocket<{
      type?: string;
      owner_app_id?: string;
      resource?: string;
      workspace_id?: string;
    }>((event) => {
      if (
        event.type === "maverick.app.data-changed" &&
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

  if (!providers.length) return children(null);
  const total = inboxes.reduce((sum, inbox) => sum + inbox.total, 0);
  const notices = inboxes.flatMap((inbox) =>
    inbox.notices.map((notice) => ({
      ...notice,
      appId: inbox.appId,
      name: inbox.name,
    })),
  );

  async function dismiss(appId: string, id: string) {
    const key = `${appId}:${id}`;
    setPending((current) => [...current, key]);
    try {
      await request(appId, { action: "notifications.dismiss", id });
      setInboxes((current) =>
        current.map((inbox) =>
          inbox.appId === appId
            ? {
                ...inbox,
                total: Math.max(0, inbox.total - 1),
                notices: inbox.notices.filter((notice) => notice.id !== id),
              }
            : inbox,
        ),
      );
      setError("");
      setRefresh((current) => current + 1);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Impossibile chiudere la notifica.",
      );
    } finally {
      setPending((current) => current.filter((value) => value !== key));
    }
  }

  return children(
    <NotificationPopover placement={placement}
      announcement={total ? `${total} notifiche da leggere` : ""}
      toggleContent={<>
        <span className="material-symbols-rounded" aria-hidden="true">
          notifications
        </span>
        <span className="bs-notifications__announcement">
          Notifiche{total > 0 ? ` (${total})` : ""}
          {error ? " · !" : ""}
        </span>
        {(total > 0 || error) && (
          <span className="bs-notifications__badge" aria-hidden="true">
            {error ? "!" : total}
          </span>
        )}
      </>}>
      {(close) => <>
        {error && (
          <p role="alert">
            {error}{" "}
            <button
              type="button"
              onClick={() => setRefresh((value) => value + 1)}
            >
              Riprova
            </button>
          </p>
        )}
        {!total && !error && <p>Nessuna notifica da leggere.</p>}
        {notices.slice(0, limit).map((notice) => (
          <article key={`${notice.appId}:${notice.id}`}>
            <small>{notice.name}</small>
            <button
              type="button"
              className="bs-notifications__open"
              onClick={() => {
                onOpenApp(notice.appId, notice.open_params || {});
                close();
              }}
            >
              {notice.title}
            </button>
            {notice.scheduled_at && (
              <time dateTime={notice.scheduled_at}>{noticeTime(notice)}</time>
            )}
            <button
              type="button"
              disabled={pending.includes(`${notice.appId}:${notice.id}`)}
              aria-label={`Chiudi notifica: ${notice.title}`}
              onClick={() => void dismiss(notice.appId, notice.id)}
            >
              Chiudi
            </button>
          </article>
        ))}
        {total > limit && (
          <button
            type="button"
            onClick={() => {
              if (limit >= notices.length) setPages((value) => value + 1);
              setLimit((value) => value + 5);
            }}
          >
            Mostra altre notifiche
          </button>
        )}
      </>}
    </NotificationPopover>,
  );
}
