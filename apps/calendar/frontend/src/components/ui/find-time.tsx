import {
  observeMaverickVisibility,
  maverickAppIsVisible,
} from "@maverick/pwa-cache";
import { useEffect, useRef, useState } from "react";
import { findFreeTime, checkAvailability } from "@/api";
import { readPreferences, t } from "@/preferences";
import type { DraftEvent } from "./calendar-types";
import { civilDays, shiftCivilDate } from "./event-editor-domain";
import { parseZonedInput, zonedInput } from "./time-layout";
import { Field } from "./event-panel-fields";
import { eventWhen } from "./event-details";

export function FindTime({
  appId,
  draft,
  onSelect,
  readOnly = false,
}: {
  appId: string;
  draft: DraftEvent | null;
  onSelect: (patch: DraftEvent) => void;
  readOnly?: boolean;
}) {
  const [slots, setSlots] = useState<
    Array<{ startTime: string; endTime: string }>
  >([]);
  const [conflicts, setConflicts] = useState<
    Array<{ title: string; startTime: string }>
  >([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const [preferencesVersion, setPreferencesVersion] = useState(0);
  const zone =
    draft?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone;
  const draftKey = JSON.stringify([
    draft?.id,
    draft?.startTime,
    draft?.endTime,
    draft?.timezone,
    draft?.attendees,
    draft?.all_day,
    preferencesVersion,
  ]);
  const firstDay = zonedInput(draft?.startTime, zone, true);
  const [from, setFrom] = useState(firstDay);
  const [to, setTo] = useState(firstDay ? shiftCivilDate(firstDay, 14) : "");
  const key = `${draftKey}:${from}:${to}:${readOnly}`;
  const currentKey = useRef(key);
  currentKey.current = key;
  const read = useRef<AbortController | null>(null);
  useEffect(() => {
    setFrom(firstDay);
    setTo(firstDay ? shiftCivilDate(firstDay, 14) : "");
  }, [draftKey]);
  useEffect(() => {
    read.current?.abort();
    setSlots([]);
    setConflicts([]);
    setError("");
    setBusy(false);
    setSearched(false);
  }, [key]);
  useEffect(() => {
    const changed = () => setPreferencesVersion((v) => v + 1);
    window.addEventListener("calendar-preferences-changed", changed);
    const stop = observeMaverickVisibility((visible) => {
      if (!visible) {
        read.current?.abort();
        setBusy(false);
      }
    });
    return () => {
      stop();
      read.current?.abort();
      window.removeEventListener("calendar-preferences-changed", changed);
    };
  }, [appId]);
  async function find() {
    if (
      readOnly ||
      !draft?.startTime ||
      !draft?.endTime ||
      !maverickAppIsVisible()
    )
      return;
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    const requestedKey = key;
    setBusy(true);
    setError("");
    setSlots([]);
    setConflicts([]);
    try {
      const start = parseZonedInput(from, zone),
        end = parseZonedInput(shiftCivilDate(to, 1), zone);
      if (
        !Number.isFinite(start.getTime()) ||
        !Number.isFinite(end.getTime()) ||
        end <= start
      )
        throw new Error(t("Choose a valid search interval"));
      const prefs = readPreferences();
      const [availability, result] = await Promise.all([
        checkAvailability(
          appId,
          {
            startTime: draft.startTime.toISOString(),
            endTime: draft.endTime.toISOString(),
            ignore_event_id: draft.id,
            attendees: draft.attendees,
          },
          controller.signal,
        ),
        findFreeTime(
          appId,
          {
            start_after: start.toISOString(),
            end_before: end.toISOString(),
            all_day: Boolean(draft.all_day),
            duration_days: civilDays(draft),
            duration_minutes: draft.all_day
              ? 30
              : Math.max(
                  1,
                  Math.ceil(
                    (draft.endTime.getTime() - draft.startTime.getTime()) /
                      60000,
                  ),
                ),
            timezone: zone,
            work_start: prefs.workStart,
            work_end: prefs.workEnd,
            work_days: prefs.workDays,
            buffer_minutes: prefs.bufferMinutes,
            ignore_event_id: draft.id,
            attendees: draft.attendees,
            limit: 5,
          },
          controller.signal,
        ),
      ]);
      if (controller.signal.aborted || currentKey.current !== requestedKey)
        return;
      setConflicts(availability.conflicts || []);
      setSlots(result.slots || []);
      setSearched(true);
    } catch (err) {
      if (!controller.signal.aborted && currentKey.current === requestedKey)
        setError(err instanceof Error ? err.message : t("Availability failed"));
    } finally {
      if (!controller.signal.aborted && currentKey.current === requestedKey)
        setBusy(false);
    }
  }
  if (readOnly) return null;
  return (
    <details>
      <summary>{t(draft?.all_day ? "Find free days" : "Find a time")}</summary>
      <div>
        <p>
          {t("Known local events only; invitee calendars may be incomplete.")}
        </p>
        <div className="calendar-editor-grid">
          <Field label="From">
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </Field>
          <Field label="To">
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </Field>
        </div>
        <p>
          {zone} ·{" "}
          {draft?.all_day
            ? `${civilDays(draft)} ${t("days")}`
            : draft?.startTime && draft.endTime
              ? `${Math.ceil((draft.endTime.getTime() - draft.startTime.getTime()) / 60000)} ${t("minutes")}`
              : ""}
        </p>
        <button
          type="button"
          disabled={
            busy ||
            !draft?.startTime ||
            !draft.endTime ||
            !Number.isFinite(draft.startTime.getTime()) ||
            draft.endTime <= draft.startTime
          }
          onClick={() => void find()}
        >
          {busy ? "…" : t(draft?.all_day ? "Find free days" : "Find a time")}
        </button>
        {error && <p role="alert">{error}</p>}
        {conflicts.map((c, i) => (
          <p key={i}>
            {t("Overlapping events")}: {c.title}
          </p>
        ))}
        {slots.map((slot) => (
          <button
            type="button"
            className="calendar-slot-choice"
            key={slot.startTime}
            onClick={() =>
              onSelect({
                startTime: new Date(slot.startTime),
                endTime: new Date(slot.endTime),
              })
            }
          >
            {t("Use this time")} ·{" "}
            {eventWhen({
              ...draft,
              id: "slot",
              title: "",
              color: "blue",
              timezone: zone,
              startTime: new Date(slot.startTime),
              endTime: new Date(slot.endTime),
            })}
          </button>
        ))}
        {!busy && !error && !slots.length && (
          <p>
            {t(
              searched
                ? "No free times in this interval"
                : "No times proposed yet",
            )}
          </p>
        )}
      </div>
    </details>
  );
}
