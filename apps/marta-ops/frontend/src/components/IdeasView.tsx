import { FormEvent, useMemo, useState } from "react";
import { IDEA_OPTIONS, labelFor } from "../options";
import type { Idea, IdeaStatus } from "../types";

export function IdeasView({
  ideas,
  query,
  saving,
  onCreate,
  onUpdate,
}: {
  ideas: Idea[];
  query: string;
  saving: boolean;
  onCreate: (idea: {
    title: string;
    pillar: string;
    note: string;
  }) => Promise<void>;
  onUpdate: (id: string, changes: Partial<Idea>) => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [pillar, setPillar] = useState("");
  const [note, setNote] = useState("");
  const visible = useMemo(
    () =>
      ideas
        .filter(
          (idea) =>
            idea.status !== "archived" &&
            [idea.title, idea.pillar, idea.note]
              .join(" ")
              .toLocaleLowerCase("it")
              .includes(query.trim().toLocaleLowerCase("it")),
        )
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [ideas, query],
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    try {
      await onCreate({ title, pillar, note });
      setTitle("");
      setPillar("");
      setNote("");
    } catch {
      // The app-level error toast owns user feedback.
    }
  }

  return (
    <section className="page ideas-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Inbox creativa</p>
          <h1>
            Idee <span className="heading-count">{visible.length}</span>
          </h1>
        </div>
      </header>
      <form className="idea-capture" onSubmit={submit}>
        <input
          aria-label="Titolo idea"
          maxLength={200}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Scrivi un’idea in una riga…"
          required
          value={title}
        />
        <input
          aria-label="Pillar"
          maxLength={100}
          onChange={(event) => setPillar(event.target.value)}
          placeholder="Pillar (facoltativo)"
          value={pillar}
        />
        <input
          aria-label="Nota"
          maxLength={1200}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Nota o hook (facoltativo)"
          value={note}
        />
        <button
          className="primary-action"
          disabled={saving || !title.trim()}
          type="submit"
        >
          Salva
        </button>
      </form>
      {visible.length ? (
        <div className="idea-list">
          {visible.map((idea) => (
            <article className="idea-row" key={idea.id}>
              <div>
                <h2>{idea.title}</h2>
                <p>
                  {[idea.pillar, idea.note].filter(Boolean).join(" · ") ||
                    "Nessuna nota"}
                </p>
              </div>
              <select
                aria-label={`Stato di ${idea.title}`}
                disabled={saving}
                onChange={(event) =>
                  void onUpdate(idea.id, {
                    status: event.target.value as IdeaStatus,
                  }).catch(() => undefined)
                }
                value={idea.status}
              >
                {IDEA_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <small>{labelFor(IDEA_OPTIONS, idea.status)}</small>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <h2>L’inbox è vuota</h2>
          <p>Quando arriva un’intuizione, una riga basta.</p>
        </div>
      )}
    </section>
  );
}
