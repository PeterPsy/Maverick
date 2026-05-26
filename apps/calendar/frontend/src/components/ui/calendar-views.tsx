import { Clock } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { ColorClasses, Event, ViewProps } from "./calendar-types"
import { EventCard } from "./calendar-event-card"
import { eventsForDate, eventsForHour, formatTime } from "./calendar-utils"

export function MonthView(props: ViewProps & { onDrop: (date: Date) => void }) {
  const firstDayOfMonth = new Date(props.currentDate.getFullYear(), props.currentDate.getMonth(), 1)
  const startDate = new Date(firstDayOfMonth)
  startDate.setDate(startDate.getDate() - startDate.getDay())
  const days = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(startDate)
    day.setDate(startDate.getDate() + index)
    return day
  })
  return (
    <Card className="overflow-hidden">
      <div className="grid grid-cols-7 border-b">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
          <div key={day} className="border-r p-2 text-center text-xs font-medium last:border-r-0 sm:text-sm">
            <span className="hidden sm:inline">{day}</span>
            <span className="sm:hidden">{day.charAt(0)}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((day) => {
          const dayEvents = eventsForDate(props.events, day)
          const isCurrentMonth = day.getMonth() === props.currentDate.getMonth()
          const isToday = day.toDateString() === new Date().toDateString()
          return (
            <div key={day.toISOString()} className={cn("min-h-20 border-b border-r p-1 transition-colors last:border-r-0 sm:min-h-24 sm:p-2", !isCurrentMonth && "bg-muted/30", "hover:bg-accent/50")} onDragOver={(event) => event.preventDefault()} onDrop={() => props.onDrop(day)}>
              <div className={cn("mb-1 flex h-5 w-5 items-center justify-center rounded-full text-xs sm:h-6 sm:w-6 sm:text-sm", isToday && "bg-primary text-primary-foreground font-semibold")}>{day.getDate()}</div>
              <div className="space-y-1">
                {dayEvents.slice(0, 3).map((event) => <EventCard key={event.id} {...props} event={event} variant="compact" />)}
                {dayEvents.length > 3 && <div className="text-[10px] text-muted-foreground sm:text-xs">+{dayEvents.length - 3} more</div>}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export function WeekView(props: ViewProps & { onDrop: (date: Date, hour: number) => void }) {
  const startOfWeek = new Date(props.currentDate)
  startOfWeek.setDate(props.currentDate.getDate() - props.currentDate.getDay())
  const weekDays = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(startOfWeek)
    day.setDate(startOfWeek.getDate() + index)
    return day
  })
  return (
    <Card className="overflow-auto">
      <div className="grid grid-cols-8 border-b">
        <div className="border-r p-2 text-center text-xs font-medium sm:text-sm">Time</div>
        {weekDays.map((day) => (
          <div key={day.toISOString()} className="border-r p-2 text-center text-xs font-medium last:border-r-0 sm:text-sm">
            <div className="hidden sm:block">{day.toLocaleDateString("en-US", { weekday: "short" })}</div>
            <div className="sm:hidden">{day.toLocaleDateString("en-US", { weekday: "narrow" })}</div>
            <div className="text-[10px] text-muted-foreground sm:text-xs">{day.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-8">
        {Array.from({ length: 24 }, (_, hour) => (
          <HourRow key={hour} hour={hour} days={weekDays} {...props} />
        ))}
      </div>
    </Card>
  )
}

function HourRow({ hour, days, ...props }: ViewProps & { hour: number; days: Date[]; onDrop: (date: Date, hour: number) => void }) {
  return (
    <>
      <div className="border-b border-r p-1 text-[10px] text-muted-foreground sm:p-2 sm:text-xs">{hour.toString().padStart(2, "0")}:00</div>
      {days.map((day) => (
        <div key={`${day.toISOString()}-${hour}`} className="min-h-12 border-b border-r p-0.5 transition-colors hover:bg-accent/50 last:border-r-0 sm:min-h-16 sm:p-1" onDragOver={(event) => event.preventDefault()} onDrop={() => props.onDrop(day, hour)}>
          <div className="space-y-1">{eventsForHour(props.events, day, hour).map((event) => <EventCard key={event.id} {...props} event={event} />)}</div>
        </div>
      ))}
    </>
  )
}

export function DayView(props: ViewProps & { onDrop: (date: Date, hour: number) => void }) {
  return (
    <Card className="overflow-auto">
      {Array.from({ length: 24 }, (_, hour) => (
        <div key={hour} className="flex border-b last:border-b-0" onDragOver={(event) => event.preventDefault()} onDrop={() => props.onDrop(props.currentDate, hour)}>
          <div className="w-14 flex-shrink-0 border-r p-2 text-xs text-muted-foreground sm:w-20 sm:p-3 sm:text-sm">{hour.toString().padStart(2, "0")}:00</div>
          <div className="min-h-16 flex-1 p-1 transition-colors hover:bg-accent/50 sm:min-h-20 sm:p-2">
            <div className="space-y-2">{eventsForHour(props.events, props.currentDate, hour).map((event) => <EventCard key={event.id} {...props} event={event} variant="detailed" />)}</div>
          </div>
        </div>
      ))}
    </Card>
  )
}

export function ListView({ events, onEventClick, getColorClasses }: { events: Event[]; onEventClick: (event: Event) => void; getColorClasses: (color: string) => ColorClasses }) {
  const sortedEvents = [...events].sort((a, b) => a.startTime.getTime() - b.startTime.getTime())
  const groupedEvents = sortedEvents.reduce(
    (acc, event) => {
      const dateKey = event.startTime.toLocaleDateString("en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      })
      if (!acc[dateKey]) acc[dateKey] = []
      acc[dateKey].push(event)
      return acc
    },
    {} as Record<string, Event[]>,
  )

  return (
    <Card className="p-3 sm:p-4">
      <div className="space-y-6">
        {Object.entries(groupedEvents).map(([date, dateEvents]) => (
          <div key={date} className="space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground sm:text-sm">{date}</h3>
            <div className="space-y-2">
              {dateEvents.map((event) => {
                const colorClasses = getColorClasses(event.color)
                return (
                  <div
                    key={event.id}
                    onClick={() => onEventClick(event)}
                    className="group cursor-pointer rounded-lg border bg-card p-3 transition-all hover:shadow-md hover:scale-[1.01] animate-in fade-in slide-in-from-bottom-2 duration-300 sm:p-4"
                  >
                    <div className="flex items-start gap-2 sm:gap-3">
                      <div className={cn("mt-1 h-2.5 w-2.5 rounded-full sm:h-3 sm:w-3", colorClasses.bg)} />
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <h4 className="font-semibold text-sm group-hover:text-primary transition-colors sm:text-base truncate">{event.title}</h4>
                            {event.description && <p className="mt-1 text-xs text-muted-foreground sm:text-sm line-clamp-2">{event.description}</p>}
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {event.category && <Badge variant="secondary" className="text-xs">{event.category}</Badge>}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground sm:gap-4 sm:text-xs">
                          <div className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {formatTime(event.startTime)} - {formatTime(event.endTime)}
                          </div>
                          {event.tags && event.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {event.tags.map((tag) => (
                                <Badge key={tag} variant="outline" className="text-[10px] h-4 sm:text-xs sm:h-5">{tag}</Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
        {sortedEvents.length === 0 && <div className="py-12 text-center text-sm text-muted-foreground sm:text-base">No events found</div>}
      </div>
    </Card>
  )
}
