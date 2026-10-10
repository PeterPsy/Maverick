import { useId, useState } from "react";
import type { DraftEvent } from "./calendar-types";
import { Field } from "./event-panel-fields";
import { t } from "@/preferences";
export function responseLabel(status?: string) {
  return t(
    (
      {
        accepted: "Accepted",
        declined: "Declined",
        tentative: "Tentative",
        needsAction: "Awaiting response",
      } as Record<string, string>
    )[status || ""] || "Response unknown",
  );
}
export function EventPeople({
  draft,
  onChange,
}: {
  draft: DraftEvent;
  onChange: (patch: DraftEvent) => void;
}) {
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const id = useId();
  const attendees = draft.attendees || [];
  const google = draft.source === "google_calendar";
  function add() {
    const email = address.trim();
    if (
      !email ||
      email.length > 120 ||
      (google && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))
    ) {
      setError(t("Enter a valid email address"));
      return;
    }
    if (attendees.some((a) => a.toLowerCase() === email.toLowerCase())) {
      setError(t("Participant already added"));
      return;
    }
    onChange({
      attendees: [...attendees, email],
      attendee_details: [
        ...(draft.attendee_details || []),
        {
          email,
          ...(name.trim() ? { displayName: name.trim() } : {}),
          ...(google ? { responseStatus: "needsAction" as const } : {}),
        },
      ],
    });
    setAddress("");
    setName("");
    setError("");
  }
  return (
    <fieldset className="calendar-editor-section">
      <legend>{t("Attendees")}</legend>
      {draft.organizer && (
        <p>
          {t("Organizer")}: {draft.organizer}
        </p>
      )}
      <ul className="calendar-people-list">
        {attendees.map((email) => {
          const person = draft.attendee_details?.find(
            (a) => a.email.toLowerCase() === email.toLowerCase(),
          );
          return (
            <li key={email}>
              <div>
                <strong>{person?.displayName || email}</strong>
                {person?.displayName && <span>{email}</span>}
                {google && (
                  <small>{responseLabel(person?.responseStatus)}</small>
                )}
              </div>
              <label>
                <input
                  type="checkbox"
                  checked={person?.optional || false}
                  onChange={(e) =>
                    onChange({
                      attendee_details: [
                        ...(draft.attendee_details || []).filter(
                          (a) => a.email.toLowerCase() !== email.toLowerCase(),
                        ),
                        { ...person, email, optional: e.target.checked },
                      ],
                    })
                  }
                />{" "}
                {t("Optional")}
              </label>
              <button
                type="button"
                aria-label={`${t("Remove participant")} ${email}`}
                onClick={() =>
                  onChange({
                    attendees: attendees.filter((a) => a !== email),
                    attendee_details: (draft.attendee_details || []).filter(
                      (a) => a.email.toLowerCase() !== email.toLowerCase(),
                    ),
                  })
                }
              >
                {t("Remove")}
              </button>
            </li>
          );
        })}
      </ul>
      <div className="calendar-editor-grid">
        <Field label={google ? "Email" : "Name or email"}>
          <input
            type={google ? "email" : "text"}
            value={address}
            maxLength={120}
            onChange={(e) => setAddress(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
        </Field>
        <Field label="Display name">
          <input
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
      </div>
      <button type="button" disabled={attendees.length >= 50} onClick={add}>
        {t("Add participant")}
      </button>
      {error && (
        <p id={id} role="alert">
          {error}
        </p>
      )}
      <p>
        {t(
          google
            ? "Google invitees require email addresses. Responses are shown as received from Google."
            : "Local participants are notes; Maverick does not send invitations.",
        )}
      </p>
    </fieldset>
  );
}
