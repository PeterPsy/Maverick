import { useEffect, useState } from "react";
import { ChatProject, ChatThread } from "../../api/client";

export function ThreadInlineActions({
  onClose,
  onDeleteThread,
  onRenameThread,
  projects,
  title,
  thread,
}: {
  onClose: () => void;
  onDeleteThread: (threadId: string) => Promise<void>;
  onRenameThread: (threadId: string, title: string, projectId: string | null) => Promise<void>;
  projects: ChatProject[];
  title: string;
  thread: ChatThread;
}) {
  const [projectId, setProjectId] = useState(thread.project_id || "");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProjectId(thread.project_id || "");
    setError(null);
  }, [thread.project_id, thread.thread_id, thread.title]);

  async function save() {
    const nextTitle = title.trim();
    if (!nextTitle) {
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      await onRenameThread(thread.thread_id, nextTitle, projectId || null);
      onClose();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save chat.");
    } finally {
      setIsSaving(false);
    }
  }

  async function remove() {
    setIsSaving(true);
    setError(null);
    try {
      await onDeleteThread(thread.thread_id);
      onClose();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete chat.");
      setIsSaving(false);
    }
  }

  return (
    <div className="bs-chat-list__inline-actions">
      <div className="bs-chat-list__inline-field">
        <span className="bs-chat-list__inline-select-frame">
          <select aria-label="Progetto" disabled={isSaving} onChange={(event) => setProjectId(event.target.value)} value={projectId}>
            <option value="">Senza progetto</option>
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
        </span>
      </div>
      {error ? <p className="bs-chat-list__inline-error">{error}</p> : null}
      <div className="bs-chat-list__inline-buttons">
        <button disabled={isSaving || !title.trim()} onClick={save} type="button">
          Salva
        </button>
        <button disabled={isSaving} onClick={onClose} type="button">
          Annulla
        </button>
        <button aria-label={`Elimina ${thread.title}`} className="bs-chat-list__inline-icon-button" disabled={isSaving} onClick={remove} title="Elimina" type="button">
          <span aria-hidden="true" className="material-symbols-rounded">delete</span>
        </button>
      </div>
    </div>
  );
}
