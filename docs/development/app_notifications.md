# Centralized app notifications

Every new or ported app must assess notification use cases: reminders, messages,
background job completion/failure, approvals, deliveries, and meaningful domain
changes. If an app needs or can use notifications, implement them through the
central Base Shell inbox. App-owned inline status can complement it; a second
app bell, private global inbox, browser timer, or hardcoded shell app branch must
not replace it. Declare only implemented notification behavior.

## Ownership and discovery

Add the following declaration to the app contract's `provides` array:

```json
{"interface":"notifications.inbox","version":"1","surfaces":["backend"]}
```

Declare `notifications` in `events.data.resources` with `enabled: true`. Publish
`{"type":"maverick.app.data-changed","resource":"notifications"}` in `app_events`
when notifications arrive, change, retract, become read, or are dismissed.
Core stamps the event's owner/workspace and trusted entrypoint `user_id`.
Persist notifications, deduplication keys, and per-user read/dismiss/action
receipts under `data/<app_id>/`. Scheduled/background producers run in app-owned
`background_tick`/recovery hooks. Browser presence must not determine delivery.
Another app can communicate with a producer through a declared `provides`/
`requires` interface; it cannot write that producer's private notification data.

Base Shell discovers every enabled authorized provider, regardless of the
active app or sidebar opt-out. One reader survives closed menus and desktop/
mobile layout changes. The bell remains available even with an empty inbox.
The app registry supplies service names and app-owned icons. A notification
cannot choose another app's identity or execute a backend URL.

## Backend contract

`notifications.list` accepts `offset` (nonnegative integer, default 0) and
`limit` (1–100, default 50). Return newest first:

```json
{
  "notifications": [{
    "id": "review-4821",
    "title": "Design review",
    "body": "Thursday · 10:00–10:30",
    "created_at": "2026-10-10T10:00:00Z",
    "read": false,
    "open_params": {"event_id":"review-4821"},
    "presentation": {
      "kind":"calendar", "date":"2026-10-15", "accent":"#ef4444",
      "attendees":["Ava Chen","Noah Kim"]
    },
    "actions": [{"id":"accept","label":"Accetta","done":"Accettato"}]
  }],
  "total": 1,
  "unread_total": 1,
  "has_more": false,
  "capabilities": {"read":true,"actions":true}
}
```

Required v1 fields remain `id`, `title`, `notifications`, `total`, and
`has_more`. `scheduled_at` (ISO timestamp), `timezone` (IANA), `body`,
`created_at`, `read`, `presentation`, and `actions` are optional.
`open_params` uses string/boolean/null values and navigates to the owning app.
`total` includes read, undismissed rows; `unread_total` covers the entire inbox,
not just the loaded page. Dismissed rows and all private receipt maps are
excluded from projections. Ids are stable within their provider; the shell
namespaces them and merges providers by `created_at`, falling back to
`scheduled_at`. Reads/actions never depend on provider credentials.

- `notifications.dismiss` accepts `id` and idempotently acknowledges it for
  the trusted user. This operation is required.
- `capabilities.read: true` advertises `notifications.read`, which accepts
  either `id` or `all: true`, never both. Keep read receipts distinct from
  dismissal. Opening a notification records a read when supported; “Segna
  lette” persists reads across all eligible providers and pages. Without the
  capability, the shell does not invent local read receipts.
- `capabilities.actions: true` advertises `notifications.action`, which
  accepts `id` and `action_id`. Validate that the actor may act on that
  notification and that the id belongs to its current action allowlist.
  Validate domain transitions and make repeat requests idempotent. Return an
  updated public `notification` with optional `action_done` when appropriate,
  and publish the resource event. Unsupported actions are hidden.

The shell filters malformed action entries once and uses that same list for
rendering and dispatch. Each valid entry needs string `id` and `label` fields;
an invalid entry must not block the remaining valid actions.

The shell only removes a card after successful dismissal and only shows action
completion confirmed by the provider. Failed writes preserve the card and offer
retry. “Chiudi visibili” dismisses the displayed rows; it does not silently
clear unloaded notifications. Events coalesce refreshes; reconnect/resume reads
recover durable state. Hidden/offline readers suspend and late results cannot
cross authenticated workspace/session boundaries. No OS push is implied.

## Live detail fields

`presentation` is data, never HTML, a callback, or a second app UI. Unknown or
malformed kinds display a generic card with the app's title/body/navigation.

| kind | Required fields | Optional fields |
| --- | --- | --- |
| `generic` | — | `accent` |
| `message` | `from`, `text` | `accent` |
| `delivery` | `steps` (1–8 labels), `step` (zero based) | `accent` |
| `ride` | `minutes`, `vehicle`, `plate` | `accent` |
| `payment` | `amount` | `currency`, `locale`, `accent` |
| `calendar` | `date` (`YYYY-MM-DD`) | `attendees`, `locale`, `accent` |
| `code` | `code` | `expires_at` (absolute ISO), `expiresIn`, `accent` |
| `flight` | `from`, `to`, `gate` | `previousGate`, `accent` |
| `fitness` | `value`, `goal`, `unit` | `streak`, `locale`, `accent` |

Use absolute `expires_at` for real codes so closing/reopening or replaying a
card cannot extend its expiry. Producers choose safe, useful preview content.
Codes support up to 20 characters; the detail wraps into additional rows when
needed so every character remains readable at narrow viewport widths.
Never expose credentials or hidden private fields merely to fill a detail.
Calendar is the current built-in provider: it produces real calendar detail,
trusted-user read receipts, and idempotent dismissal. Its domain has no inbox
approval action, so it advertises `actions: false`.

## UI integration and verification

The reusable entrypoint is
`apps/base-shell/frontend/src/components/ui/live-notification-feed.tsx`, aliased
as `@/components/ui/live-notification-feed`. This is the app's `/components/ui`
directory under its existing Vite source root; keeping it there makes shadcn
imports/discovery work without creating a repository-wide UI ownership layer.
Existing shell primitives stay in `frontend/src/ui`.

React 19 and TypeScript already exist. `components.json`, the `@` alias,
Tailwind's Vite plugin, and app-local theme mapping are installed. Feed styles
live in `frontend/src/styles/notification-feed.css`, imported separately by `main.tsx`;
utilities scan `components/ui` and the `AppNotifications.tsx` adapter (including
the registry logo's `object-contain`) and omit the global Preflight reset
according to the [Tailwind integration guidance](https://tailwindcss.com/docs/preflight#disabling-preflight).
Lucide supplies glyphs; app identity images come from the registry. No stock
photos or context providers are required.

Real providers use `managed`, server `items`, `unreadCount`, and asynchronous
callbacks. Read/done state remains authoritative in app projections. The
provided eight-kind sample and autoplay loop are kept in
`live-notification-feed.demo.tsx`; demo data and decorative backgrounds are not
mounted in the product. Production autoplay stays off. New arrivals animate,
reduced motion shows final detail immediately, and mobile touch retains visible
dismiss controls. Same-id calendar date updates restart the decorative sheet
animation so the replacement sheets reveal the current date. The popover lives
in the browser top layer and supports keyboard focus, Escape, outside dismissal,
and viewport constraints.

Verify arrivals while another app is active, repeated events/reconnect, provider
disablement, desktop/mobile (including 320px), light/dark themes, read-all beyond
a page, duplicate ids across providers, unsupported capabilities, failed writes,
actor/workspace isolation, same-id calendar date changes after arrival, codes of
6/8/20 characters with per-character clipping checks, rectangular registry logos,
malformed entries alongside valid actions, and opening the app through
`open_params`. Do not claim a producer is integrated until it emits a real
notification through this surface.
