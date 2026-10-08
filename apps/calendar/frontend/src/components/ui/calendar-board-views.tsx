import type { CalendarView, ColorClasses, Event } from "./calendar-types"
import { DayView, ListView, MonthView, WeekView } from "./calendar-views"

export function CalendarBoardViews({
  currentDate,
  events,
  getColorClasses,
  onDrop,
  onEventClick,
  onDragStart,
  onDragEnd,
  view,
  onCreateAt,
  onDayOpen,
}: {
  onCreateAt?: (date: Date, hour?: number) => void
  onDayOpen?: (date: Date) => void
  currentDate: Date
  events: Event[]
  getColorClasses: (color: string) => ColorClasses
  onDrop: (date: Date, hour?: number) => void
  onEventClick: (event: Event) => void
  onDragStart: (event: Event) => void
  onDragEnd: () => void
  view: CalendarView
}) {
  if (view === "month") {
    return (
      <MonthView
        onCreateAt={onCreateAt}
        onDayOpen={onDayOpen}
        currentDate={currentDate}
        events={events}
        onEventClick={onEventClick}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDrop={onDrop}
        getColorClasses={getColorClasses}
      />
    )
  }
  if (view === "week") {
    return (
      <WeekView
        onCreateAt={onCreateAt}
        onDayOpen={onDayOpen}
        currentDate={currentDate}
        events={events}
        onEventClick={onEventClick}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDrop={onDrop}
        getColorClasses={getColorClasses}
      />
    )
  }
  if (view === "day") {
    return (
      <DayView
        onCreateAt={onCreateAt}
        onDayOpen={onDayOpen}
        currentDate={currentDate}
        events={events}
        onEventClick={onEventClick}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDrop={onDrop}
        getColorClasses={getColorClasses}
      />
    )
  }
  return <ListView currentDate={currentDate} events={events} onEventClick={onEventClick} getColorClasses={getColorClasses} />
}
