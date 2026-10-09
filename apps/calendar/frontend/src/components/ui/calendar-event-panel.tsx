import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  type ReactNode,
} from "react";
import { X } from "lucide-react";
import { Button } from "./button";
import { Input } from "./input";
import { Label } from "./label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";
import { Textarea } from "./textarea";
import type {
  CalendarRemoteCalendar,
  CalendarSourceOption,
  ColorClasses,
  DraftEvent,
  Event,
} from "./calendar-types";
import {
  calendarSourcePatch,
  eventIsReadOnly,
  selectedCalendarSourceValue,
} from "./calendar-utils";
import { parseZonedInput, zonedInput } from "./time-layout";
import { t } from "@/preferences";

export function EventPanel(props: {
  mode: "create" | "details";
  draft: DraftEvent | Event | null;
  error: string;
  isSaving: boolean;
  canSave: boolean;
  categories: string[];
  colors: { name: string; value: string; bg: string; text: string }[];
  availableTags: string[];
  calendars?: CalendarRemoteCalendar[];
  calendarSourceOptions?: CalendarSourceOption[];
  getColorClasses: (color: string) => ColorClasses;
  setDraft: (patch: DraftEvent) => void;
  toggleTag: (tag: string) => void;
  onCreate: () => void;
  onUpdate: () => void;
  onDelete: () => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  const creating = props.mode === "create",
    draft = props.draft;
  const readOnly =
    !creating && !!draft && eventIsReadOnly(draft, props.calendars || []);
  const remoteConnection = draft?.external_refs?.provider_event_id
    ? draft.external_refs.calendar_connection_id
    : undefined;
  const recurring = !!(
    draft?.series_id || draft?.external_refs?.recurring_event_id
  );
  const sources = (props.calendarSourceOptions || []).filter(
    (option) =>
      option.writable !== false &&
      (!remoteConnection || option.connectionId === remoteConnection) &&
      (!recurring ||
        draft?.recurrence_scope === "series" ||
        option.providerCalendarId ===
          draft?.external_refs?.provider_calendar_id),
  );
  const zone =
    draft?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  const zones = Array.from(
    new Set([
      "UTC",
      zone,
      ...((
        Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
      ).supportedValuesOf?.("timeZone") || ["Europe/Rome", "America/New_York"]),
    ]),
  );
  const frequency = String(draft?.recurrence?.frequency || "").toLowerCase();
  return (
    <section
      className="calendar-event-panel"
      aria-label={t(creating ? "Create Event" : "Event Details")}
    >
      <div className="calendar-event-panel__header">
        <h2>{t(creating ? "Create Event" : "Event Details")}</h2>
      </div>
      <div className="calendar-event-panel__body">
        {props.error && (
          <div role="alert" className="calendar-event-panel__error">
            {props.error}
          </div>
        )}
        {readOnly && <p>{t("Read only")}</p>}
        <Field label="Title">
          <Input
            value={draft?.title || ""}
            onChange={(e) => props.setDraft({ title: e.target.value })}
            placeholder={t("Event title")}
            disabled={readOnly}
          />
        </Field>
        <Field label="Description">
          <Textarea
            value={draft?.description || ""}
            onChange={(e) => props.setDraft({ description: e.target.value })}
            rows={3}
            disabled={readOnly}
          />
        </Field>
        <label>
          <input
            type="checkbox"
            checked={draft?.all_day || false}
            disabled={readOnly}
            onChange={(e) => {
              const start = draft?.startTime
                ? zonedInput(draft.startTime, zone, true)
                : zonedInput(new Date(), zone, true);
              const end = new Date(`${start}T12:00:00Z`);
              end.setUTCDate(end.getUTCDate() + 1);
              props.setDraft({
                all_day: e.target.checked,
                timezone: zone,
                ...(e.target.checked
                  ? {
                      startTime: parseZonedInput(start, zone),
                      endTime: parseZonedInput(
                        end.toISOString().slice(0, 10),
                        zone,
                      ),
                    }
                  : {}),
              });
            }}
          />{" "}
          {t("All day")}
        </label>
        <DateTimeField
          label="Start Time"
          value={draft?.startTime}
          zone={zone}
          allDay={draft?.all_day}
          disabled={readOnly}
          onChange={(startTime) => props.setDraft({ startTime })}
        />
        <DateTimeField
          label="End Time"
          value={draft?.endTime}
          zone={zone}
          allDay={draft?.all_day}
          disabled={readOnly}
          onChange={(endTime) => props.setDraft({ endTime })}
        />
        {draft?.all_day && <p>{t("End date is exclusive")}</p>}
        {sources.length > 1 && (
          <Field label="Calendar">
            <Select
              value={selectedCalendarSourceValue(draft, sources)}
              disabled={readOnly || !props.canSave}
              onValueChange={(value) =>
                props.setDraft(calendarSourcePatch(draft, value, sources))
              }
            >
              <SelectTrigger aria-label={t("Calendar")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sources.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        {recurring &&
          Boolean(remoteConnection) &&
          draft?.recurrence_scope !== "series" && (
            <p>{t("Select entire series to transfer this recurring event.")}</p>
          )}
        <Field label="Busy">
          <select
            value={draft?.transparency || "opaque"}
            disabled={readOnly}
            onChange={(e) =>
              props.setDraft({
                transparency: e.target.value as "opaque" | "transparent",
              })
            }
          >
            <option value="opaque">{t("Busy")}</option>
            <option value="transparent">{t("Free")}</option>
          </select>
        </Field>
        {Boolean(
          draft?.series_id || draft?.external_refs?.recurring_event_id,
        ) && (
          <Field label="Recurrence">
            <select
              value={draft?.recurrence_scope || "occurrence"}
              disabled={readOnly}
              onChange={(e) =>
                props.setDraft({
                  recurrence_scope: e.target.value as
                    | "occurrence"
                    | "future"
                    | "series",
                })
              }
            >
              <option value="occurrence">{t("This occurrence")}</option>
              <option value="future">{t("This and following")}</option>
              <option value="series">{t("Entire series")}</option>
            </select>
          </Field>
        )}
        <details>
          <summary>{t("Advanced options")}</summary>
          <div>
            <Field label="Location">
              <Input
                disabled={readOnly}
                value={draft?.location || ""}
                onChange={(e) => props.setDraft({ location: e.target.value })}
              />
            </Field>
            <Field label="Attendees">
              <Input
                disabled={readOnly}
                value={(draft?.attendees || []).join(", ")}
                onChange={(e) =>
                  props.setDraft({
                    attendees: e.target.value
                      .split(",")
                      .map((v) => v.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="name@example.com, …"
              />
            </Field>
            <Field label="Timezone">
              <select
                disabled={readOnly}
                value={zone}
                onChange={(e) => props.setDraft({ timezone: e.target.value })}
              >
                {zones.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Status">
              <select
                disabled={readOnly}
                value={draft?.status || "confirmed"}
                onChange={(e) =>
                  props.setDraft({ status: e.target.value as Event["status"] })
                }
              >
                <option value="confirmed">{t("Confirmed")}</option>
                <option value="tentative">{t("Tentative")}</option>
                <option value="cancelled">{t("Cancelled")}</option>
              </select>
            </Field>
            <Field label="Recurrence">
              <select
                disabled={
                  readOnly ||
                  (!!draft?.series_id && draft?.recurrence_scope !== "series")
                }
                value={frequency || (draft?.recurrence?.rules ? "custom" : "")}
                onChange={(e) =>
                  props.setDraft({
                    recurrence: e.target.value
                      ? { frequency: e.target.value, count: 10 }
                      : {},
                  })
                }
              >
                <option value="">{t("None")}</option>
                {["daily", "weekly", "monthly", "yearly"].map((f) => (
                  <option key={f} value={f}>
                    {t(f[0].toUpperCase() + f.slice(1))}
                  </option>
                ))}
                {Boolean(draft?.recurrence?.rules) && (
                  <option value="custom">iCalendar</option>
                )}
              </select>
            </Field>
            {frequency && (
              <Field label="Repeat count">
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  disabled={readOnly}
                  value={Number(draft?.recurrence?.count || 10)}
                  onChange={(e) =>
                    props.setDraft({
                      recurrence: {
                        ...draft?.recurrence,
                        count: Number(e.target.value),
                      },
                    })
                  }
                />
              </Field>
            )}
            {Array.isArray(draft?.recurrence?.rules) && (
              <Field label="iCalendar">
                <Textarea
                  disabled={
                    readOnly ||
                    (!!draft?.series_id && draft?.recurrence_scope !== "series")
                  }
                  value={draft.recurrence.rules.join("\n")}
                  onChange={(e) =>
                    props.setDraft({
                      recurrence: {
                        ...draft.recurrence,
                        rules: e.target.value.split("\n").filter(Boolean),
                      },
                    })
                  }
                />
              </Field>
            )}
            {draft?.source === "google_calendar" && (
              <label>
                <input
                  type="checkbox"
                  disabled={readOnly}
                  checked={draft.reminders_use_default !== false}
                  onChange={(e) =>
                    props.setDraft({ reminders_use_default: e.target.checked })
                  }
                />
                {t("Use Google default reminders")}
              </label>
            )}
            <Field label="Reminder">
              <Input
                type="number"
                min={0}
                max={40320}
                disabled={readOnly}
                value={String(
                  (
                    draft?.reminders?.[0] as
                      | { minutes_before?: number }
                      | undefined
                  )?.minutes_before ?? "",
                )}
                onChange={(e) =>
                  props.setDraft({
                    reminders_use_default: false,
                    reminders:
                      e.target.value === ""
                        ? []
                        : [
                            {
                              method: "popup",
                              minutes_before: Number(e.target.value),
                            },
                          ],
                  })
                }
              />
            </Field>
            {draft?.source !== "google_calendar" && (
              <p>{t("Local reminders are saved in Maverick notifications, even when Calendar is closed.")}</p>
            )}
            <Field label="Category">
              <select
                disabled={readOnly}
                value={draft?.category || props.categories[0]}
                onChange={(e) => props.setDraft({ category: e.target.value })}
              >
                {Array.from(
                  new Set(
                    [...props.categories, draft?.category].filter(Boolean),
                  ),
                ).map((category) => (
                  <option key={category} value={category}>
                    {t(category!)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Color">
              <select
                disabled={readOnly}
                value={draft?.color || "blue"}
                onChange={(e) => props.setDraft({ color: e.target.value })}
              >
                {props.colors.map((color) => (
                  <option key={color.value} value={color.value}>
                    {t(color.name)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Tags">
              <div className="flex flex-wrap gap-2">
                {props.availableTags.map((tag) => (
                  <button
                    type="button"
                    disabled={readOnly}
                    key={tag}
                    aria-pressed={draft?.tags?.includes(tag) || false}
                    onClick={() => props.toggleTag(tag)}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            </Field>
          </div>
        </details>
        {props.children}
      </div>
      <div className="calendar-event-panel__footer">
        <Button
          className="calendar-event-panel__save"
          disabled={props.isSaving || !draft || readOnly || !props.canSave}
          onClick={creating ? props.onCreate : props.onUpdate}
        >
          {t(props.isSaving ? "Saving..." : "Save")}
        </Button>
        {!creating && (
          <Button
            className="calendar-event-panel__delete"
            variant="secondary"
            disabled={props.isSaving || !draft || readOnly}
            onClick={props.onDelete}
          >
            {t("Delete")}
          </Button>
        )}
        <Button
          variant="secondary"
          size="icon"
          disabled={props.isSaving}
          onClick={props.onClose}
          aria-label={t("Close")}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </Button>
      </div>
    </section>
  );
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return (
    <div className="calendar-event-panel__field">
      <Label htmlFor={id}>{t(label)}</Label>
      {isValidElement(children)
        ? cloneElement(
            children as ReactElement<{ id?: string; "aria-label"?: string }>,
            { id, "aria-label": t(label) },
          )
        : children}
    </div>
  );
}
function DateTimeField({
  label,
  value,
  zone,
  allDay,
  onChange,
  disabled,
}: {
  label: string;
  value?: Date;
  zone: string;
  allDay?: boolean;
  onChange: (date: Date) => void;
  disabled: boolean;
}) {
  return (
    <Field label={label}>
      <Input
        type={allDay ? "date" : "datetime-local"}
        step={allDay ? undefined : 900}
        value={zonedInput(value, zone, allDay)}
        disabled={disabled}
        onChange={(e) => onChange(parseZonedInput(e.target.value, zone))}
      />
    </Field>
  );
}
