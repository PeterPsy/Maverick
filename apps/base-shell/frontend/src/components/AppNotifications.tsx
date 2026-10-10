import { useState, type ReactNode } from "react";
import { NotificationPopover } from "./NotificationPopover";
import { LiveNotificationFeed } from "./ui/live-notification-feed";
import { useNotificationInbox } from "../hooks/useNotificationInbox";
import type { AppRegistryItem } from "../api";
import type { MaverickFrameScope } from "../iframePolicy";
import { noticeKey, noticeTime } from "../notificationInbox";
import {
  navigationParams,
  noticeAge,
  noticeTimestamp,
  notificationPresentation,
} from "../notificationPresentation";

/** Accessible from every app, including apps opting out of the detail sidebar. */
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
  const {
    inboxes,
    error,
    pending,
    mutate,
    retry,
    loadMore,
    readAll,
    dismissMany,
  } = useNotificationInbox(apps, scope);
  const [limit, setLimit] = useState(5);
  const total = inboxes.reduce((sum, inbox) => sum + inbox.total, 0);
  const unread = inboxes.reduce((sum, inbox) => sum + inbox.unread, 0);
  const notices = inboxes
    .flatMap((inbox) =>
      inbox.notices.map((notice) => ({
        inbox,
        notice,
        key: noticeKey(inbox.appId, notice.id),
        actions:
          inbox.capabilities.actions && Array.isArray(notice.actions)
            ? notice.actions.filter(
                (action) =>
                  action &&
                  typeof action.id === "string" &&
                  typeof action.label === "string",
              )
            : [],
      })),
    )
    .sort(
      (a, b) =>
        noticeTimestamp(b.notice) - noticeTimestamp(a.notice) ||
        a.key.localeCompare(b.key),
    );
  const visible = notices.slice(0, limit);
  const items = [...visible].reverse().map(({ inbox, notice, key, actions }) =>
    notificationPresentation(
      {
        id: key,
        app: inbox.name,
        title: notice.title,
        body:
          (typeof notice.body === "string" ? notice.body : undefined) ??
          (notice.scheduled_at ? noticeTime(notice) : undefined),
        time: noticeAge(notice),
        read: notice.read === true,
        readable: inbox.capabilities.read,
        pending:
          pending.includes(key) ||
          pending.includes(noticeKey(inbox.appId, null)),
        done:
          typeof notice.action_done === "string"
            ? notice.action_done
            : undefined,
        icon:
          inbox.logo?.kind === "image" ? (
            <img
              src={inbox.logo.value}
              alt=""
              loading="lazy"
              className="size-6 object-contain"
            />
          ) : inbox.logo?.kind === "glyph" ? (
            <span aria-hidden className="material-symbols-rounded">
              {inbox.logo.value}
            </span>
          ) : undefined,
        actions,
      },
      notice.presentation,
    ),
  );
  return children(
    <NotificationPopover
      placement={placement}
      announcement={unread ? `${unread} notifiche da leggere` : ""}
      toggleContent={
        <>
          <span className="material-symbols-rounded" aria-hidden="true">
            notifications
          </span>
          <span className="bs-notifications__announcement">
            Notifiche{unread > 0 ? ` (${unread})` : ""}
            {error ? " · !" : ""}
          </span>
          {(unread > 0 || error) && (
            <span className="bs-notifications__badge" aria-hidden="true">
              {error ? "!" : unread}
            </span>
          )}
        </>
      }
    >
      {(close) => (
        <>
          {error && (
            <p className="bs-notifications__error" role="alert">
              {error}{" "}
              <button type="button" onClick={retry}>
                Riprova
              </button>
            </p>
          )}
          <LiveNotificationFeed
            items={items}
            managed
            unreadCount={unread}
            height="min(440px, calc(100dvh - var(--notification-popover-top, 80px) - 120px))"
            onReadAll={
              inboxes.some((inbox) => inbox.capabilities.read)
                ? readAll
                : undefined
            }
            onClear={() => dismissMany(visible)}
            onOpen={(id) => {
              const entry = visible.find((value) => value.key === id);
              if (!entry) return;
              if (entry.inbox.capabilities.read && !entry.notice.read)
                void mutate(entry.inbox, entry.notice.id, "read").catch(
                  () => {},
                );
              onOpenApp(
                entry.inbox.appId,
                navigationParams(entry.notice.open_params),
              );
              close();
            }}
            onDismiss={(id) => {
              const entry = visible.find((value) => value.key === id);
              return entry
                ? mutate(entry.inbox, entry.notice.id, "dismiss")
                : undefined;
            }}
            onAction={(id, label, actionId) => {
              const entry = visible.find((value) => value.key === id);
              const action = entry?.actions.find(
                (value) => value.id === actionId && value.label === label,
              );
              if (!entry?.inbox.capabilities.actions || !action) return;
              return mutate(entry.inbox, entry.notice.id, "action", action.id);
            }}
          />
          {total > visible.length && (
            <button
              type="button"
              className="bs-notifications__more"
              onClick={() => {
                if (limit >= notices.length) loadMore();
                setLimit((value) => value + 5);
              }}
            >
              Mostra altre notifiche
            </button>
          )}
        </>
      )}
    </NotificationPopover>,
  );
}
