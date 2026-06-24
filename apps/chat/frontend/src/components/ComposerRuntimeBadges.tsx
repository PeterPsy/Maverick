import type { ProviderItem } from "../api/client";
import { ProviderSelector } from "./ProviderSelector";

type ExecutionMode = "sandbox" | "full-access";

export function ComposerRuntimeBadges({
  activeProviderId,
  disabled,
  executionMode,
  onSelectProvider,
  providers,
}: {
  activeProviderId: string;
  disabled: boolean;
  executionMode: ExecutionMode | null;
  onSelectProvider: (providerId: string) => void;
  providers: ProviderItem[];
}) {
  return (
    <div className="chatapp-composer__runtime-badges">
      <ProviderSelector activeProviderId={activeProviderId} disabled={disabled} onSelect={onSelectProvider} providers={providers} />
      {executionMode ? (
        <span
          aria-label={executionMode === "full-access" ? "Full access runtime" : "Sandbox runtime"}
          className={`chatapp-execution-chip ${executionMode === "full-access" ? "is-full-access" : "is-sandbox"}`}
          role="img"
          title={executionMode === "full-access" ? "Full access runtime" : "Sandbox runtime"}
        >
          <span aria-hidden="true" className="material-symbols-rounded">
            {executionMode === "full-access" ? "admin_panel_settings" : "lock"}
          </span>
        </span>
      ) : null}
    </div>
  );
}
