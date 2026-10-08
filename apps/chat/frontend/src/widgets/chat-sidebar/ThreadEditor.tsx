import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, Folder, LoaderCircle, Trash2 } from "lucide-react";
import type { ChatProject, ChatThread } from "../../api/client";
import "./thread-editor.css";

export function ThreadEditor({
  onClose,
  onDeleteThread,
  onRenameThread,
  onTitleChange,
  projects,
  title,
  thread,
}: {
  onClose: () => void;
  onDeleteThread: (threadId: string) => Promise<void>;
  onRenameThread: (
    threadId: string,
    title: string,
    projectId: string | null,
  ) => Promise<void>;
  onTitleChange: (title: string) => void;
  projects: ChatProject[];
  title: string;
  thread: ChatThread;
}) {
  const id = useId();
  const titleRef = useRef<HTMLInputElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);
  const wasConfirmingRef = useRef(false);
  const [projectId, setProjectId] = useState(thread.project_id || "");
  const [pendingAction, setPendingAction] = useState<"save" | "delete" | null>(
    null,
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isPending = pendingAction !== null;
  const hasChanges =
    title.trim() !== thread.title || projectId !== (thread.project_id || "");

  useEffect(() => {
    titleRef.current?.select();
  }, []);

  useEffect(() => {
    if (wasConfirmingRef.current && !confirmDelete) deleteRef.current?.focus();
    wasConfirmingRef.current = confirmDelete;
  }, [confirmDelete]);

  async function save() {
    if (isPending || confirmDelete || !title.trim() || !hasChanges) return;
    setPendingAction("save");
    setError(null);
    try {
      await onRenameThread(thread.thread_id, title.trim(), projectId || null);
      onClose();
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "Unable to save chat.",
      );
    } finally {
      setPendingAction(null);
    }
  }

  async function remove() {
    if (isPending) return;
    setPendingAction("delete");
    setError(null);
    try {
      await onDeleteThread(thread.thread_id);
      onClose();
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : "Unable to delete chat.",
      );
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <form
      aria-label={`Edit ${thread.title}`}
      aria-busy={isPending}
      className="bs-chat-thread-editor"
      onKeyDown={(event) => {
        if (event.key !== "Escape" || isPending) return;
        event.preventDefault();
        event.stopPropagation();
        if (confirmDelete) {
          setConfirmDelete(false);
          setError(null);
        } else onClose();
      }}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <label className="bs-chat-thread-editor__field" htmlFor={`${id}-title`}>
        <span>Title</span>
        <input
          aria-label={`Edit title ${thread.title}`}
          autoFocus
          disabled={isPending}
          id={`${id}-title`}
          onChange={(event) => {
            setError(null);
            onTitleChange(event.target.value);
          }}
          ref={titleRef}
          required
          value={title}
        />
      </label>
      <label className="bs-chat-thread-editor__field" htmlFor={`${id}-project`}>
        <span>Project</span>
        <span className="bs-chat-thread-editor__project">
          <Folder aria-hidden="true" size={15} strokeWidth={1.5} />
          <select
            disabled={isPending}
            id={`${id}-project`}
            onChange={(event) => {
              setError(null);
              setProjectId(event.target.value);
            }}
            value={projectId}
          >
            <option value="">No project</option>
            {thread.project_id &&
            !projects.some(
              (project) => project.project_id === thread.project_id,
            ) ? (
              <option value={thread.project_id}>Current project</option>
            ) : null}
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </select>
          <ChevronDown aria-hidden="true" size={14} />
        </span>
      </label>
      {error ? (
        <p className="bs-chat-thread-editor__error" role="alert">
          {error}
        </p>
      ) : null}
      {confirmDelete ? (
        <div className="bs-chat-thread-editor__confirmation">
          <p>Delete this chat?</p>
          <div className="bs-chat-thread-editor__footer">
            <button
              autoFocus
              disabled={isPending}
              onClick={() => {
                setConfirmDelete(false);
                setError(null);
              }}
              type="button"
            >
              Keep chat
            </button>
            <button
              className="is-danger"
              disabled={isPending}
              onClick={() => void remove()}
              type="button"
            >
              {pendingAction === "delete" ? (
                <LoaderCircle
                  aria-hidden="true"
                  className="is-spinning"
                  size={14}
                />
              ) : (
                <Trash2 aria-hidden="true" size={14} />
              )}
              {pendingAction === "delete" ? "Deleting…" : "Delete chat"}
            </button>
          </div>
        </div>
      ) : (
        <div className="bs-chat-thread-editor__footer">
          <button
            aria-label={`Delete ${thread.title}`}
            className="bs-chat-thread-editor__delete"
            disabled={isPending}
            onClick={() => {
              setError(null);
              setConfirmDelete(true);
            }}
            title="Delete chat"
            ref={deleteRef}
            type="button"
          >
            <Trash2 aria-hidden="true" size={15} strokeWidth={1.5} />
          </button>
          <button disabled={isPending} onClick={onClose} type="button">
            Cancel
          </button>
          <button
            className="is-primary"
            disabled={isPending || !title.trim() || !hasChanges}
            type="submit"
          >
            {pendingAction === "save" ? (
              <LoaderCircle
                aria-hidden="true"
                className="is-spinning"
                size={14}
              />
            ) : (
              <Check aria-hidden="true" size={14} />
            )}
            {pendingAction === "save" ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </form>
  );
}
