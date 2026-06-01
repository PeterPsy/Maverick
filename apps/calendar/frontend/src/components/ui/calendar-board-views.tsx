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
}: {
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
