import { t, readPreferences, formatCalendarDate } from "@/preferences";
import { timelineEvents } from "./time-layout";
import { observeMaverickVisibility } from "@maverick/pwa-cache";
import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ColorClasses, Event, ViewProps } from "./calendar-types";
import { EventCard } from "./calendar-event-card";
import {
  eventDisplayDate,
  eventsForDate,
  eventsForListDate,
  formatTime,
  isSameCalendarDate,
} from "./calendar-utils";

export function MonthView(props: ViewProps & { onDrop: (date: Date) => void }) {
  const firstDayOfMonth = new Date(
    props.currentDate.getFullYear(),
    props.currentDate.getMonth(),
    1,
  );
  const startDate = new Date(firstDayOfMonth);
  startDate.setDate(
    startDate.getDate() -
      ((startDate.getDay() - readPreferences().weekStartsOn + 7) % 7),
  );
  const days = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(startDate);
    day.setDate(startDate.getDate() + index);
    return day;
  });
  return (
    <Card className="overflow-visible">
      <div className="grid grid-cols-7 border-b">
        {Array.from({ length: 7 }, (_, i) =>
          formatCalendarDate(
            new Date(2026, 5, 7 + ((i + readPreferences().weekStartsOn) % 7)),
            { weekday: "short" },
          ),
        ).map((day) => (
          <div
            key={day}
            className="border-r p-2 text-center text-xs font-medium last:border-r-0 sm:text-sm"
          >
            {day}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((day) => {
          const dayEvents = eventsForDate(props.events, day);
          const isCurrentMonth =
            day.getMonth() === props.currentDate.getMonth();
          const isToday = day.toDateString() === new Date().toDateString();
          return (
            <div
              key={day.toISOString()}
              className={cn(
                "min-h-20 border-b border-r p-1 transition-colors last:border-r-0 sm:min-h-24 sm:p-2",
                !isCurrentMonth && "bg-muted/30",
                "hover:bg-accent/50",
              )}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => props.onDrop(day)}
            >
              <button
                type="button"
                aria-label={`${t("New event")} ${formatCalendarDate(day, { dateStyle: "full" })}`}
                onClick={() => props.onCreateAt?.(day)}
                className={cn(
                  "mb-1 flex h-5 w-5 items-center justify-center rounded-full text-xs sm:h-6 sm:w-6 sm:text-sm",
                  isToday && "bg-primary text-primary-foreground font-semibold",
                )}
              >
                {day.getDate()}
              </button>
              <div className="space-y-1">
                {dayEvents.slice(0, 3).map((event) => (
                  <EventCard
                    key={event.id}
                    {...props}
                    event={event}
                    variant="compact"
                  />
                ))}
                {dayEvents.length > 3 && (
                  <button
                    type="button"
                    className="text-[10px] text-muted-foreground sm:text-xs"
                    onClick={() => props.onDayOpen?.(day)}
                  >
                    +{dayEvents.length - 3} {t("List")}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function WeekView(
  props: ViewProps & { onDrop: (date: Date, hour: number) => void },
) {
  const start = new Date(props.currentDate);
  start.setDate(
    start.getDate() -
      ((start.getDay() - readPreferences().weekStartsOn + 7) % 7),
  );
  const days = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(start);
    date.setDate(start.getDate() + i);
    return date;
  });
  return <TimeView {...props} days={days} />;
}
export function DayView(
  props: ViewProps & { onDrop: (date: Date, hour: number) => void },
) {
  return <TimeView {...props} days={[props.currentDate]} />;
}
function TimeView({
  days,
  ...props
}: ViewProps & { days: Date[]; onDrop: (date: Date, hour: number) => void }) {
  const now = useCurrentMinuteDate();
  return (
    <Card className="calendar-timeline-scroll">
      <div
        className="calendar-timeline"
        style={{
          gridTemplateColumns: `54px repeat(${days.length}, minmax(${days.length > 1 ? 100 : 180}px, 1fr))`,
        }}
      >
        <div className="calendar-timeline-heading">{t("Time")}</div>
        {days.map((day) => (
          <button
            type="button"
            key={day.toDateString()}
            className="calendar-timeline-heading"
            onClick={() => props.onDayOpen?.(day)}
          >
            {formatCalendarDate(day, {
              weekday: "short",
              day: "numeric",
              month: "short",
            })}
          </button>
        ))}
        <div className="calendar-timeline-heading calendar-all-day-label">{t("All day")}</div>
        {days.map((day) => (
          <div
            key={day.toDateString()}
            className="calendar-all-day"
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => props.onDrop(day, 0)}
          >
            {eventsForDate(props.events, day)
              .filter((e) => e.all_day)
              .map((event) => (
                <EventCard
                  key={event.id}
                  {...props}
                  event={event}
                  variant="compact"
                />
              ))}
          </div>
        ))}
        <div className="calendar-hours">
          {Array.from({ length: 24 }, (_, hour) => (
            <div key={hour}>{formatTime(new Date(2026, 1, 1, hour))}</div>
          ))}
        </div>
        {days.map((day) => (
          <div key={day.toDateString()} className="calendar-day-column">
            {Array.from({ length: 96 }, (_, quarter) => (
              <button
                type="button"
                key={quarter}
                className="calendar-quarter"
                aria-label={`${t("New event")} ${formatCalendarDate(day, { dateStyle: "short" })} ${Math.floor(quarter / 4)}:${String((quarter % 4) * 15).padStart(2, "0")}`}
                onClick={() => props.onCreateAt?.(day, quarter / 4)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  props.onDrop(day, quarter / 4);
                }}
              />
            ))}
            {timelineEvents(props.events, day).map((row) => (
              <div
                key={row.event.id}
                className="calendar-timed-event"
                style={{
                  top: `${(row.start / 1440) * 100}%`,
                  height: `${(Math.max(15, row.end - row.start) / 1440) * 100}%`,
                  left: `${(row.column / row.columns) * 100}%`,
                  width: `${100 / row.columns}%`,
                }}
              >
                <EventCard {...props} event={row.event} variant="detailed" />
              </div>
            ))}
            {isSameCalendarDate(day, now) && (
              <div
                aria-hidden="true"
                className="calendar-current-time-marker"
                style={{
                  top: `${((now.getHours() * 60 + now.getMinutes()) / 1440) * 100}%`,
                }}
              />
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function useCurrentMinuteDate() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let timer: number | undefined;
    const stop = observeMaverickVisibility((visible) => {
      window.clearTimeout(timer);
      if (!visible) return;
      const tick = () => {
        setNow(new Date());
        timer = window.setTimeout(tick, 60000 - (Date.now() % 60000));
      };
      tick();
    });
    return () => {
      stop();
      window.clearTimeout(timer);
    };
  }, []);

  return now;
}

export function ListView({
  currentDate,
  events,
  onEventClick,
  getColorClasses,
}: {
  currentDate: Date;
  events: Event[];
  onEventClick: (event: Event) => void;
  getColorClasses: (color: string) => ColorClasses;
}) {
  const listEvents = eventsForListDate(events, currentDate);
  const groupedEvents = listEvents.reduce(
    (acc, event) => {
      const dateKey = formatCalendarDate(eventDisplayDate(event), {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      });
      if (!acc[dateKey]) acc[dateKey] = [];
      acc[dateKey].push(event);
      return acc;
    },
    {} as Record<string, Event[]>,
  );

  return (
    <Card className="p-3 sm:p-4">
      <div className="space-y-6">
        {Object.entries(groupedEvents).map(([date, dateEvents]) => (
          <div key={date} className="space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground sm:text-sm">
              {date}
            </h3>
            <div className="space-y-2">
              {dateEvents.map((event) => {
                const colorClasses = getColorClasses(event.color);
                return (
                  <div
                    key={event.id}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onEventClick(event);
                      }
                    }}
                    onClick={() => onEventClick(event)}
                    className="group cursor-pointer rounded-lg border bg-card p-3 transition-all hover:shadow-md hover:scale-[1.01] animate-in fade-in slide-in-from-bottom-2 duration-300 sm:p-4"
                  >
                    <div className="flex items-start gap-2 sm:gap-3">
                      <div
                        className={cn(
                          "mt-1 h-2.5 w-2.5 rounded-full sm:h-3 sm:w-3",
                          colorClasses.bg,
                        )}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <h4 className="font-semibold text-sm group-hover:text-primary transition-colors sm:text-base truncate">
                              {event.title}
                            </h4>
                            {event.description && (
                              <p className="mt-1 text-xs text-muted-foreground sm:text-sm line-clamp-2">
                                {event.description}
                              </p>
                            )}
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {event.category && (
                              <Badge variant="secondary" className="text-xs">
                                {event.category}
                              </Badge>
                            )}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground sm:gap-4 sm:text-xs">
                          <div className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {event.all_day
                              ? t("All day")
                              : `${formatTime(event.startTime)} – ${formatTime(event.endTime)}`}
                          </div>
                          {event.tags && event.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {event.tags.map((tag) => (
                                <Badge
                                  key={tag}
                                  variant="outline"
                                  className="text-[10px] h-4 sm:text-xs sm:h-5"
                                >
                                  {tag}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {listEvents.length === 0 && (
          <div className="py-12 text-center text-sm text-muted-foreground sm:text-base">
            {t("No events found")}
          </div>
        )}
      </div>
    </Card>
  );
}
