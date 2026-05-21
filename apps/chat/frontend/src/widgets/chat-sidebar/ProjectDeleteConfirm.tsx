import type { PendingProjectDeletion } from "./useChatSidebarState";

export function ProjectDeleteConfirm({
  isPending,
  onCancel,
  onConfirm,
  pendingDeletion,
}: {
  isPending: boolean;
  onCancel: () => void;
  onConfirm: (projectId: string) => Promise<void>;
  pendingDeletion: PendingProjectDeletion;
}) {
  return (
    <div className="bs-chat-project-delete-confirm" role="alert">
      <p className="bs-chat-project-delete-confirm__message">{pendingDeletion.message}</p>
      <div className="bs-chat-project-delete-confirm__actions">
        <button className="bs-chat-project-delete-confirm__button" disabled={isPending} onClick={onCancel} type="button">
          Cancel
        </button>
        <button
          className="bs-chat-project-delete-confirm__button is-danger"
          disabled={isPending}
          onClick={() => void onConfirm(pendingDeletion.projectId)}
          type="button"
        >
          Delete
        </button>
      </div>
    </div>
  );
}
