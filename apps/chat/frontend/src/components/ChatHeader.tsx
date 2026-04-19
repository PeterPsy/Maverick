import type { ProviderItem } from "../api/client";
import { ProviderSelector } from "./ProviderSelector";

export function ChatHeader({
  activeProvider,
  activeProviderId,
  disabled,
  executionMode,
  onCreateChat,
  onSelectProvider,
  providers,
  runtimeStatus,
  title,
}: {
  activeProvider: ProviderItem | null;
  activeProviderId: string;
  disabled: boolean;
  executionMode: string;
  onCreateChat: () => void;
  onSelectProvider: (providerId: string) => void;
  providers: ProviderItem[];
  runtimeStatus: string;
  title: string;
}) {
  return (
    <header className="chat-ui-surface chatapp-chat-panel__meta">
      <div className="chatapp-chat-panel__meta-copy">
        <span className="chatapp-chat-panel__meta-name">{title}</span>
        <span className="chatapp-chat-panel__meta-detail">{activeProvider?.label || "Codex"}</span>
        <span className="chatapp-chat-panel__meta-separator" aria-hidden="true">
          ·
        </span>
        <span className="chatapp-chat-panel__meta-detail">{runtimeStatus}</span>
      </div>
      <div className="chatapp-chat-panel__meta-actions">
        <button
          aria-label="Nuova chat"
          className="chatapp-chat-panel__icon-action"
          disabled={disabled}
          onClick={onCreateChat}
          title="Nuova chat"
          type="button"
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            add
          </span>
        </button>
        <ProviderSelector activeProviderId={activeProviderId} disabled={disabled} onSelect={onSelectProvider} providers={providers} />
        <div className="chatapp-badge-row">
          <span className={`chat-ui-badge ${activeProvider?.status === "available" ? "chat-ui-badge--success" : "chat-ui-badge--warning"}`}>
            {activeProvider?.status || "provider"}
          </span>
          <span className="chat-ui-badge chat-ui-badge--secondary">{executionMode}</span>
        </div>
      </div>
    </header>
  );
}
