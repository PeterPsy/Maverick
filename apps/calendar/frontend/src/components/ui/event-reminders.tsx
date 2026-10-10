import type { DraftEvent } from "./calendar-types";
import { Field } from "./event-panel-fields";
import { t } from "@/preferences";
type Reminder = { method: string; minutes_before: number };
export function EventReminders({
  draft,
  onChange,
}: {
  draft: DraftEvent;
  onChange: (patch: DraftEvent) => void;
}) {
  const google = draft.source === "google_calendar";
  const reminders = (draft.reminders || []) as Reminder[];
  const defaults = google && draft.reminders_use_default !== false;
  function update(index: number, patch: Partial<Reminder>) {
    onChange({
      reminders_use_default: false,
      reminders: reminders.map((r, i) =>
        i === index ? { ...r, ...patch } : r,
      ),
    });
  }
  return (
    <fieldset className="calendar-editor-section">
      <legend>{t("Reminders")}</legend>
      {google && (
        <label>
          <input
            type="checkbox"
            checked={defaults}
            onChange={(e) =>
              onChange({ reminders_use_default: e.target.checked })
            }
          />{" "}
          {t("Use Google default reminders")}
        </label>
      )}
      {!defaults && (
        <>
          {reminders.map((reminder, i) => (
            <div key={i} className="calendar-reminder-row">
              <Field label="Minutes before">
                <input
                  type="number"
                  min={0}
                  max={40320}
                  value={reminder.minutes_before}
                  onChange={(e) =>
                    update(i, { minutes_before: Number(e.target.value) })
                  }
                />
              </Field>
              <Field label="Delivery">
                <select
                  value={reminder.method}
                  onChange={(e) => update(i, { method: e.target.value })}
                >
                  <option value="popup">{t("Notification")}</option>
                  {google && <option value="email">Email</option>}
                  {!["popup", "email"].includes(reminder.method) && (
                    <option value={reminder.method}>{reminder.method}</option>
                  )}
                </select>
              </Field>
              <button
                type="button"
                aria-label={`${t("Remove reminder")} ${i + 1}`}
                onClick={() =>
                  onChange({
                    reminders_use_default: false,
                    reminders: reminders.filter((_, j) => j !== i),
                  })
                }
              >
                {t("Remove")}
              </button>
            </div>
          ))}
          {!reminders.length && <p>{t("No reminders")}</p>}
          <button
            type="button"
            disabled={reminders.length >= 5}
            onClick={() =>
              onChange({
                reminders_use_default: false,
                reminders: [
                  ...reminders,
                  { method: "popup", minutes_before: 10 },
                ],
              })
            }
          >
            {t("Add reminder")}
          </button>
        </>
      )}
      {!google && (
        <p>
          {t(
            "Local reminders are saved in Maverick notifications, even when Calendar is closed.",
          )}
        </p>
      )}
    </fieldset>
  );
}
