import type { ChatUsageSummary, ProviderItem } from "../api/client";
import { ChatUsageBadge } from "./ChatUsageBadge";
import { ProviderSelector } from "./ProviderSelector";

type ExecutionMode = "sandbox" | "full-access";

export function ComposerRuntimeBadges({
  activeProviderId,
  disabled,
  executionMode,
  locked = false,
  onSelectProvider,
  onReasoningEffortChange,
  providers,
  reasoningEffort = "",
  usage = null,
}: {
  activeProviderId: string;
  disabled: boolean;
  executionMode: ExecutionMode | null;
  locked?: boolean;
  onSelectProvider: (providerId: string, reasoningEffort?: string) => void;
  onReasoningEffortChange: (effort: string) => void;
  providers: ProviderItem[];
  reasoningEffort?: string;
  usage?: ChatUsageSummary | null;
}) {
  const selectedProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
  const certificateExpiring = agenticCertificateExpiringSoon(selectedProvider?.agentic_certificate_expires_at);
  const contained = selectedProvider?.agentic_containment_status === "NO-GO";
  const destinationLabel = selectedProvider?.agentic_data_destination?.display_label || "destination unavailable";
  const showAgenticProfile = Boolean(
    selectedProvider?.workspace_profile_binding_id && (!locked || contained),
  );
  const governanceTitle = [
    selectedProvider?.label,
    contained ? "NO-GO" : selectedProvider?.agentic_rollout_status,
    `destination ${destinationLabel}`,
    selectedProvider?.agentic_egress_policy
      ? `egress ${selectedProvider.agentic_egress_policy.policy_id}@${selectedProvider.agentic_egress_policy.revision} [${selectedProvider.agentic_egress_policy.allowed_remote_data_classes.join(", ") || "none"}]`
      : null,
    selectedProvider?.agentic_data_policy
      ? `data collection ${selectedProvider.agentic_data_policy.collection} · ZDR ${selectedProvider.agentic_data_policy.require_zdr ? "required" : "not required"}`
      : null,
    `certificate ${selectedProvider?.agentic_certificate_posture?.effective_status || selectedProvider?.agentic_certificate_status || "unknown"}`,
    selectedProvider?.agentic_certificate_posture?.eligibility
      ? `certificate eligibility ${selectedProvider.agentic_certificate_posture.eligibility}`
      : null,
  ].filter(Boolean).join(" · ");
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
      <ChatUsageBadge usage={usage} />
      {showAgenticProfile ? (
        <span
          aria-label={contained ? `NO-GO agentic profile; ${destinationLabel}` : undefined}
          className={`chatapp-agentic-profile-chip ${certificateExpiring || contained ? "is-warning" : ""}`}
          title={governanceTitle}
        >
          <span aria-hidden="true" className="material-symbols-rounded">verified_user</span>
          {contained
            ? `NO-GO · ${destinationLabel}`
            : selectedProvider?.agentic_rollout_status || "Agentic"}
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
