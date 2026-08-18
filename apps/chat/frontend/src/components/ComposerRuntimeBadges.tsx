import type { ProviderItem } from "../api/client";
import { ProviderSelector } from "./ProviderSelector";

type ExecutionMode = "sandbox" | "full-access";

export function ComposerRuntimeBadges({
  activeProviderId,
  disabled,
  executionMode,
  locked = false,
  onSelectProvider,
  onReasoningEffortChange,
  onSyntheticDataConfirmedChange,
  providers,
  syntheticDataConfirmationRequired = false,
  syntheticDataConfirmed = false,
  reasoningEffort = "",
}: {
  activeProviderId: string;
  disabled: boolean;
  executionMode: ExecutionMode | null;
  locked?: boolean;
  onSelectProvider: (providerId: string, reasoningEffort?: string) => void;
  onReasoningEffortChange: (effort: string) => void;
  onSyntheticDataConfirmedChange?: (confirmed: boolean) => void;
  providers: ProviderItem[];
  syntheticDataConfirmationRequired?: boolean;
  syntheticDataConfirmed?: boolean;
  reasoningEffort?: string;
}) {
  const selectedProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
  const certificateExpiring = agenticCertificateExpiringSoon(selectedProvider?.agentic_certificate_expires_at);
  return (
    <div className="chatapp-composer__runtime-badges">
      <ProviderSelector
        activeProviderId={activeProviderId}
        disabled={disabled}
        locked={locked}
        onReasoningEffortChange={onReasoningEffortChange}
        onSelect={onSelectProvider}
        providers={providers}
        reasoningEffort={reasoningEffort}
      />
      {syntheticDataConfirmationRequired ? (
        locked ? (
          <span className="chatapp-synthetic-data-chip is-pinned" title="This pinned preview session is restricted to synthetic data">
            <span aria-hidden="true" className="material-symbols-rounded">science</span>
            Synthetic preview
          </span>
        ) : (
          <label className={`chatapp-synthetic-data-chip ${syntheticDataConfirmed ? "is-confirmed" : ""}`}>
            <input
              checked={syntheticDataConfirmed}
              disabled={disabled}
              onChange={(event) => onSyntheticDataConfirmedChange?.(event.currentTarget.checked)}
              type="checkbox"
            />
            <span aria-hidden="true" className="material-symbols-rounded">science</span>
            Synthetic data only
          </label>
        )
      ) : null}
      {selectedProvider?.workspace_profile_binding_id ? (
        <span
          className={`chatapp-agentic-profile-chip ${certificateExpiring ? "is-warning" : ""}`}
          title={[
            locked ? "Model, reasoning and permissions are fixed for this chat" : "Workspace agentic profile",
            selectedProvider.agentic_rollout_status,
            `certificate ${selectedProvider.agentic_certificate_status || "unknown"}`,
            `${selectedProvider.agentic_allowed_tool_handles?.length || 0} tools`,
          ].filter(Boolean).join(" · ")}
        >
          <span aria-hidden="true" className="material-symbols-rounded">verified_user</span>
          {locked ? "Fixed for this chat" : selectedProvider.agentic_rollout_status || "Agentic"}
          {certificateExpiring ? " · certificate expiring" : ""}
        </span>
      ) : null}
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

function agenticCertificateExpiringSoon(value: string | null | undefined): boolean {
  if (!value) return false;
  const remaining = new Date(value).getTime() - Date.now();
  return Number.isFinite(remaining) && remaining <= 7 * 86_400_000;
}
