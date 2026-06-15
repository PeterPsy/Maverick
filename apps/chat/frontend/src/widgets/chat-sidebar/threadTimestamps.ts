import type { ChatThread } from "../../api/client";

type TimestampCandidate = {
  iso: string;
  value: number;
};

type FormatTimestampOptions = {
  locale?: string;
  timeZone?: string;
};

const DEFAULT_TIMESTAMP_LOCALE = "it-IT";
const timestampFormatters = new Map<string, Intl.DateTimeFormat>();

function timestampValue(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function timestampCandidates(thread: ChatThread): TimestampCandidate[] {
  return [thread.last_user_message_at, thread.last_completed_response_at, thread.updated_at, thread.created_at]
    .map((iso) => ({ iso: iso || "", value: timestampValue(iso) }))
    .filter((candidate) => candidate.iso && candidate.value > 0)
    .sort((left, right) => right.value - left.value);
}

function timestampFormatter({ locale = DEFAULT_TIMESTAMP_LOCALE, timeZone }: FormatTimestampOptions): Intl.DateTimeFormat {
  const key = `${locale}:${timeZone || ""}`;
  const cached = timestampFormatters.get(key);
  if (cached) {
    return cached;
  }
  const formatter = new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    month: "short",
    ...(timeZone ? { timeZone } : {}),
  });
  timestampFormatters.set(key, formatter);
  return formatter;
}

export function threadLastMessageTimestamp(thread: ChatThread): number {
  return timestampCandidates(thread)[0]?.value || 0;
}

export function threadLastMessageIso(thread: ChatThread): string {
  return timestampCandidates(thread)[0]?.iso || "";
}

export function formatThreadLastMessageTimestamp(thread: ChatThread, options: FormatTimestampOptions = {}): string {
  const value = threadLastMessageTimestamp(thread);
  if (!value) {
    return "";
  }
  const parts = new Map(timestampFormatter(options).formatToParts(new Date(value)).map((part) => [part.type, part.value]));
  const day = parts.get("day") || "";
  const month = (parts.get("month") || "").replace(/\.$/, "");
  const hour = parts.get("hour") || "";
  const minute = parts.get("minute") || "";
  return [day, month, hour && minute ? `${hour}:${minute}` : ""].filter(Boolean).join(" ");
}
