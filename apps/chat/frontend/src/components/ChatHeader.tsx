import type { ProviderItem } from "../api/client";
import { ProviderSelector } from "./ProviderSelector";

export function ChatHeader({
  activeProviderId,
  disabled,
  executionMode,
  onSelectProvider,
  providers,
}: {
  activeProviderId: string;
  disabled: boolean;
  executionMode: string;
  onSelectProvider: (providerId: string) => void;
  providers: ProviderItem[];
}) {
  return (
    <header className="chat-ui-surface chatapp-chat-panel__meta">
      <div className="chatapp-chat-panel__meta-actions">
        <ProviderSelector activeProviderId={activeProviderId} disabled={disabled} onSelect={onSelectProvider} providers={providers} />
        <div className="chatapp-badge-row">
          <span className={`chatapp-execution-chip ${executionMode === "full-access" ? "is-full-access" : "is-sandbox"}`}>
            <span aria-hidden="true" className="material-symbols-rounded">
              {executionMode === "full-access" ? "admin_panel_settings" : "lock"}
            </span>
            {executionMode}
          </span>
        </div>
      </div>
    </header>
  );
}
