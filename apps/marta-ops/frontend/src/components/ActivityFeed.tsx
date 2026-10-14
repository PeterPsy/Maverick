import type { FormEvent } from "react";
import { useState } from "react";
import { Icon } from "../Icon";
import type { Activity } from "../types";

export function ActivityFeed({
  entries,
  saving = false,
  onNote,
}: {
  entries: Activity[];
  saving?: boolean;
  onNote?: (text: string) => Promise<void>;
}) {
  const [note, setNote] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!onNote || !note.trim()) return;
    try {
      await onNote(note.trim());
      setNote("");
    } catch {
      /* Retain the note for retry. */
    }
  }
  return (
    <div className="activity-feed">
      {onNote && (
        <form className="note-capture" onSubmit={submit}>
          <label className="field">
            <span>Aggiungi una nota</span>
            <textarea
              aria-label="Nuova nota"
              maxLength={4000}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Un dettaglio da ricordare…"
              rows={3}
              value={note}
            />
          </label>
          <button
            className="secondary-action"
            disabled={saving || !note.trim()}
            type="submit"
          >
            Salva nota
          </button>
        </form>
      )}
      {entries.length ? (
        <ol className="timeline">
          {[...entries]
            .sort((a, b) => b.created_at.localeCompare(a.created_at))
            .slice(0, 50)
            .map((entry) => (
              <li key={entry.id}>
                <span className="timeline-icon">
                  <Icon
                    name={entry.kind === "note" ? "note" : "work"}
                    size={14}
                  />
                </span>
                <div>
                  <strong>{entry.title}</strong>
                  {entry.text && <p>{entry.text}</p>}
                  <time dateTime={entry.created_at}>
                    {new Intl.DateTimeFormat("it-IT", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(entry.created_at))}
                  </time>
                </div>
              </li>
            ))}
        </ol>
      ) : (
        <p className="muted-message">La cronologia apparirà qui.</p>
      )}
    </div>
  );
}
