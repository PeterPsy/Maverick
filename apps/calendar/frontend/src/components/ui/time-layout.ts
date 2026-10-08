import type { Event } from "./calendar-types";
export function navigateMonth(
  date: Date,
  direction: number,
  selectedDay = date.getDate(),
) {
  const first = new Date(date.getFullYear(), date.getMonth() + direction, 1);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  first.setDate(Math.min(selectedDay, last));
  return first;
}
export function moveStart(event: Event, day: Date, hour?: number) {
  const start = new Date(day);
  if (hour === undefined)
    start.setHours(
      event.startTime.getHours(),
      event.startTime.getMinutes(),
      event.startTime.getSeconds(),
      0,
    );
  else start.setHours(Math.floor(hour), Math.round((hour % 1) * 60), 0, 0);
  return start;
}
export function timelineEvents(events: Event[], day: Date) {
  const start = new Date(day);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  const rows = events
    .filter((e) => !e.all_day && e.startTime < end && e.endTime > start)
    .map((event) => ({
      event,
      start:
        event.startTime < start
          ? 0
          : event.startTime.getHours() * 60 + event.startTime.getMinutes(),
      end:
        event.endTime >= end
          ? 1440
          : event.endTime.getHours() * 60 + event.endTime.getMinutes(),
      column: 0,
      columns: 1,
    }))
    .sort((a, b) => a.start - b.start || b.end - a.end);
  let group: typeof rows = [],
    groupEnd = 0;
  const finish = () => {
    const count = Math.max(1, ...group.map((r) => r.column + 1));
    group.forEach((r) => (r.columns = count));
  };
  for (const row of rows) {
    if (group.length && row.start >= groupEnd) {
      finish();
      group = [];
    }
    const used = new Set(
      group.filter((r) => r.end > row.start).map((r) => r.column),
    );
    while (used.has(row.column)) row.column++;
    group.push(row);
    groupEnd = Math.max(...group.map((r) => r.end));
  }
  finish();
  return rows;
}
export function zonedInput(
  date: Date | undefined,
  timezone: string,
  dateOnly = false,
) {
  if (!date || !Number.isFinite(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (key: string) => parts.find((p) => p.type === key)?.value;
  const value = `${get("year")}-${get("month")}-${get("day")}`;
  return dateOnly ? value : `${value}T${get("hour")}:${get("minute")}`;
}
export function parseZonedInput(value: string, timezone: string) {
  if (!value) return new Date(NaN);
  const civil = value.length === 10 ? `${value}T00:00` : value;
  const target = Date.parse(`${civil}:00Z`);
  let time = target;
  for (let i = 0; i < 4; i++) {
    const represented = Date.parse(
      `${zonedInput(new Date(time), timezone)}:00Z`,
    );
    const delta = target - represented;
    if (!delta) return new Date(time);
    time += delta;
  }
  return new Date(NaN); // A civil time skipped by daylight saving is invalid.
}

export function movedEventTimes(event: Event, day: Date, hour?: number) {
  if (!event.all_day) {
    const startTime = moveStart(event, day, hour);
    return {
      startTime,
      endTime: new Date(
        startTime.getTime() +
          event.endTime.getTime() -
          event.startTime.getTime(),
      ),
    };
  }
  const zone = event.timezone || "UTC";
  const civil = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
  const days = Math.round(
    (Date.parse(zonedInput(event.endTime, zone, true)) -
      Date.parse(zonedInput(event.startTime, zone, true))) /
      86400000,
  );
  const end = new Date(`${civil}T12:00Z`);
  end.setUTCDate(end.getUTCDate() + days);
  return {
    startTime: parseZonedInput(civil, zone),
    endTime: parseZonedInput(end.toISOString().slice(0, 10), zone),
  };
}
