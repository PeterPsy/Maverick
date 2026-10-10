import type {
  LiveNotification,
  NotificationBase,
} from "./components/ui/live-notification-feed";
import type { Notice } from "./notificationInbox";

const string = (value: unknown): value is string => typeof value === "string";
const number = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(string);
export function noticeTimestamp(notice: Notice) {
  const time = Date.parse(notice.created_at ?? notice.scheduled_at ?? "");
  return Number.isFinite(time) ? time : 0;
}
export function noticeAge(notice: Notice) {
  if (!notice.created_at) return "";
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - noticeTimestamp(notice)) / 60000),
  );
  if (minutes < 1) return "ora";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  return `${Math.floor(minutes / 1440)}g`;
}
/** Provider data can choose a detail, never override shell identity or callbacks. */
export function notificationPresentation(
  base: NotificationBase,
  data: Notice["presentation"],
): LiveNotification {
  const p = data ?? {};
  const locale =
    string(p.locale) &&
    (() => {
      try {
        return Boolean(Intl.getCanonicalLocales(p.locale).length);
      } catch {
        return false;
      }
    })()
      ? p.locale
      : "it-IT";
  const common = { ...base, accent: string(p.accent) ? p.accent : undefined };
  switch (p.kind) {
    case "message":
      if (string(p.from) && string(p.text))
        return { ...common, kind: "message", from: p.from, text: p.text };
      break;
    case "delivery":
      if (
        strings(p.steps) &&
        p.steps.length &&
        p.steps.length <= 8 &&
        number(p.step)
      )
        return { ...common, kind: "delivery", steps: p.steps, step: p.step };
      break;
    case "ride":
      if (number(p.minutes) && string(p.vehicle) && string(p.plate))
        return {
          ...common,
          kind: "ride",
          minutes: Math.max(0, p.minutes),
          vehicle: p.vehicle,
          plate: p.plate,
        };
      break;
    case "payment":
      if (number(p.amount))
        return {
          ...common,
          kind: "payment",
          amount: p.amount,
          currency: string(p.currency) ? p.currency : "EUR",
          locale,
        };
      break;
    case "calendar": {
      if (
        !string(p.date) ||
        !/^\d{4}-\d{2}-\d{2}$/.test(p.date) ||
        !Number.isFinite(Date.parse(p.date))
      )
        break;
      return {
        ...common,
        kind: "calendar",
        date: p.date,
        attendees: strings(p.attendees) ? p.attendees : undefined,
        locale,
      };
    }
    case "code":
      if (string(p.code) && p.code.length <= 20)
        return {
          ...common,
          kind: "code",
          code: p.code,
          expiresIn: number(p.expiresIn) ? Math.max(0, p.expiresIn) : undefined,
          expiresAt:
            string(p.expires_at) && Number.isFinite(Date.parse(p.expires_at))
              ? p.expires_at
              : undefined,
        };
      break;
    case "flight":
      if (
        string(p.from) &&
        string(p.to) &&
        string(p.gate) &&
        p.gate.length <= 8
      )
        return {
          ...common,
          kind: "flight",
          from: p.from,
          to: p.to,
          gate: p.gate,
          previousGate: string(p.previousGate) ? p.previousGate : undefined,
        };
      break;
    case "fitness":
      if (number(p.value) && number(p.goal) && string(p.unit))
        return {
          ...common,
          kind: "fitness",
          value: p.value,
          goal: p.goal,
          unit: p.unit,
          streak: number(p.streak) ? p.streak : undefined,
          locale,
        };
      break;
  }
  return { ...common, kind: "generic" };
}
export function navigationParams(
  value: unknown,
): Record<string, string | boolean | null> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      ([, v]) => v === null || typeof v === "string" || typeof v === "boolean",
    ),
  );
}
