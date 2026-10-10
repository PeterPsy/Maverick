import type { DraftEvent } from "./calendar-types";
import { parseZonedInput, zonedInput } from "./time-layout";
export const weekdays = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
export function recurrenceConfig(draft: DraftEvent) {
  const value = draft.recurrence || {};
  const rules = Array.isArray(value.rules) ? (value.rules as string[]) : [];
  const rule = rules.find((line) => line.startsWith("RRULE:"));
  const fields: Record<string, string> = Object.fromEntries(
    (rule?.slice(6) || "")
      .split(";")
      .filter(Boolean)
      .map((part) => part.split("=")),
  );
  const until = fields.UNTIL?.replace(
    /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/,
    "$1-$2-$3T$4:$5:$6Z",
  );
  const end = value.until || until;
  const untilDate = end ? new Date(String(end)) : undefined;
  return {
    frequency: String(fields.FREQ || value.frequency || "").toLowerCase(),
    interval: Number(fields.INTERVAL || value.interval || 1),
    count: Number(fields.COUNT || value.count || 10),
    ending: fields.COUNT || value.count ? "count" : end ? "until" : "never",
    until: /^\d{8}$/.test(fields.UNTIL || "")
      ? fields.UNTIL.replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3")
      : untilDate && Number.isFinite(untilDate.getTime())
        ? zonedInput(untilDate, draft.timezone || "UTC", true)
        : "",
    days: (fields.BYDAY || "").split(",").filter(Boolean),
    custom:
      rules.filter((line) => line.startsWith("RRULE:")).length > 1 ||
      Boolean(
        fields.FREQ &&
          !["DAILY", "WEEKLY", "MONTHLY", "YEARLY"].includes(fields.FREQ),
      ) ||
      Boolean(fields.BYDAY && fields.FREQ !== "WEEKLY") ||
      Boolean(fields.UNTIL && !/^(\d{8}|\d{8}T\d{6}Z)$/.test(fields.UNTIL)) ||
      Object.keys(fields).some(
        (key) =>
          !["FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST"].includes(
            key,
          ),
      ) ||
      Boolean(fields.BYDAY?.split(",").some((day) => !weekdays.includes(day))),
    extras: rules.filter((line) => !line.startsWith("RRULE:")),
    fields,
  };
}
export function updateRecurrence(
  draft: DraftEvent,
  patch: Partial<ReturnType<typeof recurrenceConfig>>,
): Record<string, unknown> {
  const config = { ...recurrenceConfig(draft), ...patch };
  if (!config.frequency) return {};
  let rule = `RRULE:FREQ=${config.frequency.toUpperCase()};INTERVAL=${config.interval}`;
  if (config.frequency === "weekly" && config.days.length)
    rule += `;BYDAY=${config.days.join(",")}`;
  if (config.fields.WKST) rule += `;WKST=${config.fields.WKST}`;
  if (config.ending === "count") rule += `;COUNT=${config.count}`;
  if (config.ending === "until" && config.until) {
    const date = parseZonedInput(
      `${config.until}T23:59`,
      draft.timezone || "UTC",
    );
    rule += `;UNTIL=${
      draft.all_day
        ? config.until.replace(/-/g, "")
        : date
            .toISOString()
            .replace(/[-:]/g, "")
            .replace(/\.\d{3}Z$/, "Z")
    }`;
  }
  const retained = Object.fromEntries(
    Object.entries(draft.recurrence || {}).filter(
      ([key]) =>
        !["frequency", "interval", "count", "until", "rules"].includes(key),
    ),
  );
  return { ...retained, rules: [rule, ...config.extras] };
}
