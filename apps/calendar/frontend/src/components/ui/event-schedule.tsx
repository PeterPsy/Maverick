import { useRef } from "react";
import { t } from "@/preferences";
import { Field, DateTimeField } from "./event-panel-fields";
import { parseZonedInput, zonedInput } from "./time-layout";
import {
  civilDays,
  moveDraftStart,
  shiftCivilDate,
  toggleAllDay,
  changeDraftTimezone,
} from "./event-editor-domain";
import type { EventPanelProps } from "./event-panel-types";
export function EventSchedule(
  props: EventPanelProps & { draft: NonNullable<EventPanelProps["draft"]> },
) {
  const draft = props.draft;
  const timed = useRef<{ startTime: Date; endTime: Date } | undefined>(
    undefined,
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
  return (
    <fieldset className="calendar-editor-section">
      <legend>{t("When")}</legend>
      <label>
        <input
          type="checkbox"
          checked={draft.all_day || false}
          onChange={(e) => {
            if (e.target.checked && draft.startTime && draft.endTime)
              timed.current = {
                startTime: draft.startTime,
                endTime: draft.endTime,
              };
            props.setDraft(
              toggleAllDay(draft, e.target.checked, timed.current),
            );
          }}
        />{" "}
        {t("All day")}
      </label>
      <div className="calendar-editor-grid">
        <DateTimeField
          label={draft.all_day ? "First day" : "Start Time"}
          value={draft.startTime}
          zone={zone}
          allDay={draft.all_day}
          onChange={(start) => props.setDraft(moveDraftStart(draft, start))}
        />
        <DateTimeField
          label={draft.all_day ? "Last day included" : "End Time"}
          value={
            draft.all_day &&
            draft.endTime &&
            Number.isFinite(draft.endTime.getTime())
              ? parseZonedInput(
                  shiftCivilDate(zonedInput(draft.endTime, zone, true), -1),
                  zone,
                )
              : draft.endTime
          }
          zone={zone}
          allDay={draft.all_day}
          onChange={(end) =>
            props.setDraft({
              endTime:
                draft.all_day && Number.isFinite(end.getTime())
                  ? parseZonedInput(
                      shiftCivilDate(zonedInput(end, zone, true), 1),
                      zone,
                    )
                  : end,
            })
          }
        />
      </div>
      <p>
        {draft.all_day
          ? `${civilDays(draft)} ${t("days")}`
          : draft.startTime && draft.endTime
            ? `${Math.round((draft.endTime.getTime() - draft.startTime.getTime()) / 60000)} ${t("minutes")}`
            : ""}
      </p>
      <Field label="Timezone">
        <select
          value={zone}
          onChange={(e) =>
            props.setDraft(changeDraftTimezone(draft, e.target.value))
          }
        >
          {zones.map((z) => (
            <option key={z}>{z}</option>
          ))}
        </select>
      </Field>
      <p>
        {t(
          draft.all_day
            ? "Changing timezone keeps the same civil dates."
            : "Changing timezone keeps the same instant; the displayed clock time changes.",
        )}
      </p>
    </fieldset>
  );
}
