import { t, readPreferences } from "@/preferences";
import type { DraftEvent } from "./calendar-types";
import { Field } from "./event-panel-fields";
import {
  recurrenceConfig,
  updateRecurrence,
  weekdays,
} from "./recurrence-editor-domain";
export function recurrenceSummary(draft: DraftEvent) {
  const config = recurrenceConfig(draft);
  if (!config.frequency)
    return t(
      draft.series_id || draft.external_refs?.recurring_event_id
        ? "Repeating event"
        : "None",
    );
  if (config.custom) return t("Custom recurrence");
  const frequency = t(
    (
      {
        daily: "Daily",
        weekly: "Weekly",
        monthly: "Monthly",
        yearly: "Yearly",
      } as Record<string, string>
    )[config.frequency] || "Custom recurrence",
  );
  const ending =
    config.ending === "count"
      ? `${config.count} ${t("occurrences")}`
      : config.ending === "until"
        ? `${t("Until")} ${config.until}`
        : t("No end date");
  return [
    frequency,
    config.interval > 1 ? `${t("Every")} ${config.interval}` : "",
    config.days.map((day) => dayName(day)).join(", "),
    ending,
  ]
    .filter(Boolean)
    .join(" · ");
}
function dayName(day: string) {
  return new Intl.DateTimeFormat(readPreferences().locale, {
    weekday: "short",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(2026, 9, 12 + weekdays.indexOf(day))));
}
export function EventRecurrence({
  draft,
  onChange,
}: {
  draft: DraftEvent;
  onChange: (patch: DraftEvent) => void;
}) {
  const config = recurrenceConfig(draft);
  const occurrence = Boolean(
    draft.series_id || draft.external_refs?.recurring_event_id,
  );
  const disabled =
    occurrence && (draft.recurrence_scope || "occurrence") === "occurrence";
  const update = (patch: Partial<typeof config>) =>
    onChange({ recurrence: updateRecurrence(draft, patch) });
  return (
    <fieldset className="calendar-editor-section">
      <legend>{t("Recurrence")}</legend>
      {occurrence && (
        <Field label="Apply changes to">
          <select
            value={draft.recurrence_scope || "occurrence"}
            onChange={(e) =>
              onChange({
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
      <p>{recurrenceSummary(draft)}</p>
      {disabled && (
        <p>
          {t(
            "Edit this and following or the entire series to change repetition.",
          )}
        </p>
      )}
      {!config.custom && (
        <>
          <Field label="Frequency">
            <select
              disabled={disabled}
              value={config.frequency}
              onChange={(e) => update({ frequency: e.target.value })}
            >
              <option value="">{t("None")}</option>
              {["daily", "weekly", "monthly", "yearly"].map((f) => (
                <option key={f} value={f}>
                  {t(f[0].toUpperCase() + f.slice(1))}
                </option>
              ))}
            </select>
          </Field>
          {config.frequency && (
            <>
              <Field label="Repeat every">
                <input
                  type="number"
                  min={1}
                  max={10000}
                  disabled={disabled}
                  value={config.interval}
                  onChange={(e) => update({ interval: Number(e.target.value) })}
                />
              </Field>
              {config.frequency === "weekly" && (
                <fieldset className="calendar-weekdays">
                  <legend>{t("Days")}</legend>
                  {weekdays.map((day) => (
                    <label key={day}>
                      <input
                        type="checkbox"
                        disabled={disabled}
                        checked={config.days.includes(day)}
                        onChange={(e) =>
                          update({
                            days: e.target.checked
                              ? [...config.days, day]
                              : config.days.filter((d) => d !== day),
                          })
                        }
                      />
                      {dayName(day)}
                    </label>
                  ))}
                </fieldset>
              )}
              <Field label="Ends">
                <select
                  disabled={disabled}
                  value={config.ending}
                  onChange={(e) =>
                    update({
                      ending: e.target.value,
                      until:
                        config.until ||
                        draft.startTime?.toISOString().slice(0, 10) ||
                        "",
                    })
                  }
                >
                  <option value="never">{t("No end date")}</option>
                  <option value="count">{t("After occurrences")}</option>
                  <option value="until">{t("On date")}</option>
                </select>
              </Field>
              {config.ending === "count" && (
                <Field label="Repeat count">
                  <input
                    type="number"
                    disabled={disabled}
                    min={1}
                    max={10000}
                    value={config.count}
                    onChange={(e) => update({ count: Number(e.target.value) })}
                  />
                </Field>
              )}
              {config.ending === "until" && (
                <Field label="Until">
                  <input
                    type="date"
                    disabled={disabled}
                    value={config.until}
                    onChange={(e) => {
                      if (e.target.value) update({ until: e.target.value });
                    }}
                  />
                </Field>
              )}
            </>
          )}
        </>
      )}
      <details>
        <summary>{t("Advanced recurrence rules")}</summary>
        <Field label="iCalendar">
          <textarea
            disabled={disabled}
            value={((draft.recurrence?.rules as string[]) || []).join("\n")}
            onChange={(e) =>
              onChange({
                recurrence: {
                  ...draft.recurrence,
                  rules: e.target.value.split("\n").filter(Boolean),
                },
              })
            }
          />
        </Field>
      </details>
    </fieldset>
  );
}
