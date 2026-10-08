import { useState } from "react";
import { readPreferences, savePreferences, t } from "@/preferences";
export function CalendarSettings() {
  const [preferences, setPreferences] = useState(readPreferences);
  function update(patch: Parameters<typeof savePreferences>[0]) {
    setPreferences(savePreferences(patch));
  }
  return (
    <details className="calendar-settings">
      <summary>{t("Settings")}</summary>
      <div>
        <label>
          {t("Language")}
          <select
            value={preferences.locale}
            onChange={(e) =>
              update({ locale: e.target.value as "it-IT" | "en-US" })
            }
          >
            <option value="it-IT">Italiano</option>
            <option value="en-US">English</option>
          </select>
        </label>
        <label>
          {t("First weekday")}
          <select
            value={preferences.weekStartsOn}
            onChange={(e) =>
              update({ weekStartsOn: Number(e.target.value) as 0 | 1 })
            }
          >
            <option value={1}>{t("Monday")}</option>
            <option value={0}>{t("Sunday")}</option>
          </select>
        </label>
        <label>
          {t("Time format")}
          <select
            value={String(preferences.hour12)}
            onChange={(e) => update({ hour12: e.target.value === "true" })}
          >
            <option value="false">24h</option>
            <option value="true">12h</option>
          </select>
        </label>
        <label>
          {t("Working hours")}
          <input
            type="time"
            value={preferences.workStart}
            onChange={(e) => update({ workStart: e.target.value })}
          />
          <input
            type="time"
            aria-label={t("End Time")}
            value={preferences.workEnd}
            onChange={(e) => update({ workEnd: e.target.value })}
          />
        </label>
        <label>
          {t("Buffer minutes")}
          <input
            type="number"
            min={0}
            max={120}
            value={preferences.bufferMinutes}
            onChange={(e) =>
              update({
                bufferMinutes: Math.max(
                  0,
                  Math.min(120, Number(e.target.value)),
                ),
              })
            }
          />
        </label>
        <fieldset>
          <legend>{t("Working hours")}</legend>
          {Array.from({ length: 7 }, (_, day) => (
            <label key={day}>
              <input
                type="checkbox"
                checked={preferences.workDays.includes(day)}
                onChange={(e) =>
                  update({
                    workDays: e.target.checked
                      ? [...preferences.workDays, day]
                      : preferences.workDays.filter((d) => d !== day),
                  })
                }
              />
              {new Date(2026, 5, 7 + day).toLocaleDateString(
                preferences.locale,
                { weekday: "short" },
              )}
            </label>
          ))}
        </fieldset>
      </div>
    </details>
  );
}
