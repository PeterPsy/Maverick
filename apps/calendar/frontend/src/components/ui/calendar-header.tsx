import { t, formatCalendarDate } from "@/preferences"
import { CalendarSettings } from "./calendar-settings"
import type { ReactNode } from "react"
import { Calendar, ChevronLeft, ChevronRight, Clock, Grid3x3, List, Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { CalendarView } from "./calendar-types"

export function Header({
  onCreate,
  view,
  currentDate,
  setView,
  navigateDate,
  setToday,
  searchQuery,
  setSearchQuery,
  filters,
}: {
  onCreate: () => void
  view: CalendarView
  currentDate: Date
  setView: (value: CalendarView) => void
  navigateDate: (direction: "prev" | "next") => void
  setToday: () => void
  searchQuery: string
  setSearchQuery: (value: string) => void
  filters?: ReactNode
}) {
  const title =
    view === "month"
      ? formatCalendarDate(currentDate, { month: "long", year: "numeric" })
      : view === "week"
        ? `${t("Week")} · ${formatCalendarDate(currentDate, { month: "short", day: "numeric" })}`
        : view === "day"
          ? formatCalendarDate(currentDate, { weekday: "long", month: "long", day: "numeric", year: "numeric" })
          : `${t("List")} · ${formatCalendarDate(currentDate, { month: "long", day: "numeric", year: "numeric" })}`

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center justify-between gap-3 sm:justify-start sm:gap-4">
          <h2 className="min-w-0 flex-1 truncate text-xl font-semibold sm:flex-none sm:text-2xl">{title}</h2>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" aria-label={t("Previous")} onClick={() => navigateDate("prev")} className="h-8 w-8 flex-shrink-0">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="icon" onClick={setToday} className="h-8 w-8 flex-shrink-0 sm:hidden" aria-label={t("Today")}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
            </Button>
            <div className="hidden sm:block">
              <Button variant="outline" size="sm" onClick={setToday}>
                {t("Today")}
              </Button>
            </div>
            <Button variant="outline" size="icon" aria-label={t("Next")} onClick={() => navigateDate("next")} className="h-8 w-8 flex-shrink-0">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="hidden sm:flex sm:items-center lg:justify-end">
          <ViewControls view={view} setView={setView} mode="desktop" />
        </div>
      </div>
      <div className="flex items-center gap-2"><Button onClick={onCreate}>{t("New event")}</Button><CalendarSettings /></div>
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div className="relative w-full min-w-[14rem] lg:max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input aria-label={t("Search events...")} placeholder={t("Search events...")} value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} className="pl-9 pr-9" />
          {searchQuery && (
            <Button variant="ghost" size="icon" className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2" aria-label={t("Clear search")} onClick={() => setSearchQuery("")}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
        <div className="flex min-w-0 items-center gap-2 sm:hidden">
          <ViewControls view={view} setView={setView} mode="mobile" />
          {filters ? <div className="min-w-0">{filters}</div> : null}
        </div>
        {filters ? <div className="hidden min-w-0 sm:block lg:flex lg:justify-end">{filters}</div> : null}
      </div>
    </div>
  )
}

function ViewControls({
  view,
  setView,
  mode,
}: {
  view: CalendarView
  setView: (value: CalendarView) => void
  mode: "mobile" | "desktop"
}) {
  if (mode === "mobile") {
    return (
      <div className="w-32 flex-shrink-0">
        <Select value={view} onValueChange={(value) => setView(value as CalendarView)}>
          <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="month"><IconLabel icon={<Calendar className="h-4 w-4" />} label={t("Month")} /></SelectItem>
            <SelectItem value="week"><IconLabel icon={<Grid3x3 className="h-4 w-4" />} label={t("Week")} /></SelectItem>
            <SelectItem value="day"><IconLabel icon={<Clock className="h-4 w-4" />} label={t("Day")} /></SelectItem>
            <SelectItem value="list"><IconLabel icon={<List className="h-4 w-4" />} label={t("List")} /></SelectItem>
          </SelectContent>
        </Select>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1 rounded-lg border bg-background p-1">
      {[
        ["month", Calendar, "Month"],
        ["week", Grid3x3, "Week"],
        ["day", Clock, "Day"],
        ["list", List, "List"],
      ].map(([value, Icon, label]) => (
        <Button key={String(value)} variant={view === value ? "secondary" : "ghost"} size="sm" onClick={() => setView(value as CalendarView)} className="h-8">
          <Icon className="h-4 w-4" />
          <span className="ml-1">{t(String(label))}</span>
        </Button>
      ))}
    </div>
  )
}

function IconLabel({ icon, label }: { icon: ReactNode; label: string }) {
  return <div className="flex items-center gap-2">{icon}{label}</div>
}
