import { useRef, type ReactNode } from "react"
import { CalendarDays, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import type { CalendarRemoteCalendar, CalendarSourceOption, ColorClasses, DraftEvent, Event } from "./calendar-types"
import { calendarSourcePatch, eventIsReadOnly, inputDate, selectedCalendarSourceValue } from "./calendar-utils"

export function EventPanel(props: {
  mode: "create" | "details"
  draft: DraftEvent | Event | null
  error: string
  isSaving: boolean
  categories: string[]
  colors: { name: string; value: string; bg: string; text: string }[]
  availableTags: string[]
  calendars?: CalendarRemoteCalendar[]
  calendarSourceOptions?: CalendarSourceOption[]
  getColorClasses: (color: string) => ColorClasses
  setDraft: (patch: DraftEvent) => void
  toggleTag: (tag: string) => void
  onCreate: () => void
  onUpdate: () => void
  onDelete: () => void
  onClose: () => void
}) {
  const isCreating = props.mode === "create"
  const draft = props.draft
  const sourceOptions = props.calendarSourceOptions || []
  const availableSourceOptions = isCreating ? sourceOptions.filter((option) => option.writable !== false) : sourceOptions
  const isReadOnly = !isCreating && draft ? eventIsReadOnly(draft, props.calendars || []) : false

  return (
    <section className="calendar-event-panel" aria-label={isCreating ? "Create event" : "Event details"}>
      <div className="calendar-event-panel__header">
        <div>
          <h2>{isCreating ? "Create Event" : "Event Details"}</h2>
        </div>
      </div>

      <div className="calendar-event-panel__body">
        {props.error && <div className="calendar-event-panel__error">{props.error}</div>}
        <Field label="Title"><Input value={draft?.title || ""} onChange={(event) => props.setDraft({ title: event.target.value })} placeholder="Event title" disabled={isReadOnly} /></Field>
        <Field label="Description"><Textarea value={draft?.description || ""} onChange={(event) => props.setDraft({ description: event.target.value })} placeholder="Event description" rows={3} disabled={isReadOnly} /></Field>
        <DateTimeField label="Start Time" value={draft?.startTime} onChange={(value) => props.setDraft({ startTime: value })} disabled={isReadOnly} />
        <DateTimeField label="End Time" value={draft?.endTime} onChange={(value) => props.setDraft({ endTime: value })} disabled={isReadOnly} />
        {availableSourceOptions.length > 1 && (
          <Field label={isCreating ? "Account / Calendar" : "Calendar"}>
            <Select
              value={selectedCalendarSourceValue(draft, availableSourceOptions)}
              onValueChange={(value) => props.setDraft(calendarSourcePatch(draft, value, availableSourceOptions))}
              disabled={isReadOnly}
            >
              <SelectTrigger><SelectValue placeholder={isCreating ? "Select account or calendar" : "Select calendar"} /></SelectTrigger>
              <SelectContent>
                {availableSourceOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        <Field label="Category">
          <Select value={draft?.category} onValueChange={(value) => props.setDraft({ category: value })} disabled={isReadOnly}>
            <SelectTrigger><SelectValue placeholder="Select category" /></SelectTrigger>
            <SelectContent>{props.categories.map((category) => <SelectItem key={category} value={category}>{category}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Color">
          <Select value={draft?.color} onValueChange={(value) => props.setDraft({ color: value })} disabled={isReadOnly}>
            <SelectTrigger><SelectValue placeholder="Select color" /></SelectTrigger>
            <SelectContent>
              {props.colors.map((color) => (
                <SelectItem key={color.value} value={color.value}>
                  <div className="flex items-center gap-2"><div className={cn("h-4 w-4 rounded", color.bg)} />{color.name}</div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Tags">
          <div className="flex flex-wrap gap-2">
            {props.availableTags.map((tag) => {
              const selected = draft?.tags?.includes(tag)
              return <Badge key={tag} variant={selected ? "default" : "outline"} className={cn(!isReadOnly && "cursor-pointer transition-all hover:scale-105")} onClick={() => !isReadOnly && props.toggleTag(tag)}>{tag}</Badge>
            })}
          </div>
        </Field>
      </div>

      <div className="calendar-event-panel__footer">
        <Button className="calendar-event-panel__save" disabled={props.isSaving || !draft || isReadOnly} onClick={isCreating ? props.onCreate : props.onUpdate}>{props.isSaving ? "Saving..." : "Save"}</Button>
        {!isCreating && <Button className="calendar-event-panel__delete" variant="secondary" disabled={props.isSaving || !draft || isReadOnly} onClick={props.onDelete}>Delete</Button>}
        <Button className="calendar-event-panel__close" variant="secondary" size="icon" disabled={props.isSaving} onClick={props.onClose} aria-label="Close">
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="calendar-event-panel__field"><Label>{label}</Label>{children}</div>
}

function DateTimeField({ label, value, onChange, disabled = false }: { label: string; value: Date | undefined; onChange: (value: Date) => void; disabled?: boolean }) {
  const inputRef = useRef<HTMLInputElement>(null)

  function openPicker() {
    const input = inputRef.current
    if (!input) return
    input.focus()
    if (typeof input.showPicker === "function") {
      try {
        input.showPicker()
      } catch {
        // Some browsers reject showPicker after the native input already handled the click.
      }
    }
  }

  return (
    <Field label={label}>
      <div className="calendar-event-panel__datetime" onClick={disabled ? undefined : openPicker}>
        <Input
          ref={inputRef}
          type="datetime-local"
          value={inputDate(value)}
          onChange={(event) => onChange(new Date(event.target.value))}
          className="calendar-event-panel__datetime-input"
          disabled={disabled}
        />
        <CalendarDays className="calendar-event-panel__datetime-icon" aria-hidden="true" />
      </div>
    </Field>
  )
}
