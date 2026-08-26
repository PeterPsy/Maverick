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
  const effective = selectedProvider?.agentic_effective_capabilities || null;
  const effectiveCapabilities = effective?.capabilities;
  const effectiveExecutionMode = effective?.execution_mode || executionMode;
  const hasAgenticProfile = Boolean(selectedProvider?.workspace_profile_binding_id);
  const effectiveAuthorityUnavailable = hasAgenticProfile && effective?.status !== "active";
  const policyLimited = Boolean(
    hasAgenticProfile &&
    effective?.status === "active" &&
    effectiveExecutionMode === "full-access" &&
    (!effectiveCapabilities?.filesystem_write || !effectiveCapabilities?.shell),
  );
  const executionBadge = effectiveAuthorityUnavailable
    ? {
        ariaLabel: "Runtime authority unavailable",
        className: "is-sandbox",
        icon: "gpp_bad",
        title: `Runtime authority unavailable · ${effective?.reason_code || "server capability snapshot missing"}`,
      }
    : policyLimited
      ? {
          ariaLabel: "Policy-limited runtime",
          className: "is-sandbox",
          icon: "policy",
          title: "Full-access boundary with server-enforced capability restrictions",
        }
      : {
          ariaLabel: effectiveExecutionMode === "full-access" ? "Full access runtime" : "Sandbox runtime",
          className: effectiveExecutionMode === "full-access" ? "is-full-access" : "is-sandbox",
          icon: effectiveExecutionMode === "full-access" ? "admin_panel_settings" : "lock",
          title: effectiveExecutionMode === "full-access" ? "Full access runtime" : "Sandbox runtime",
        };
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
    effective ? `effective authority ${effective.status} · snapshot ${effective.snapshot_digest}` : null,
    effective?.execution_mode ? `execution ${effective.execution_mode}` : null,
    effectiveCapabilities
      ? `filesystem read ${yesNo(effectiveCapabilities.filesystem_read)} / write ${yesNo(effectiveCapabilities.filesystem_write)} · shell ${yesNo(effectiveCapabilities.shell)} · CLI ${yesNo(effectiveCapabilities.cli)} · MCP ${yesNo(effectiveCapabilities.mcp)}`
      : null,
    effectiveCapabilities
      ? `skills ${yesNo(effectiveCapabilities.skill_catalog)} · app references ${yesNo(effectiveCapabilities.app_references)} · attachments ${effectiveCapabilities.attachment_modalities.join(", ") || "none"} · confirmations ${yesNo(effectiveCapabilities.confirmations)} · recovery ${yesNo(effectiveCapabilities.recovery)}`
      : null,
    effective?.provider
      ? `provider ${effective.provider.provider_id || "unknown"} · upstream ${(effective.provider.effective_upstream_ids || []).join(", ") || "none"} · health ${effective.provider.health_status || "unknown"}`
      : null,
    effective?.data_policy
      ? `effective data policy ${(effective.data_policy.allowed_remote_data_classes || []).join(", ") || "none"} · collection ${effective.data_policy.collection || "deny"} · ZDR ${effective.data_policy.require_zdr ? "required" : "not required"}`
      : null,
    effective?.certificate
      ? `effective certificate ${effective.certificate.certificate_id || "unknown"} · suite ${effective.certificate.suite_id || "unknown"}@${effective.certificate.suite_version || "unknown"} · expires ${effective.certificate.expires_at || "unknown"}`
      : null,
    effective?.tcb?.posture ? `TCB ${effective.tcb.posture}` : null,
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
          aria-label={executionBadge.ariaLabel}
          className={`chatapp-execution-chip ${executionBadge.className}`}
          role="img"
          title={executionBadge.title}
        >
          <span aria-hidden="true" className="material-symbols-rounded">{executionBadge.icon}</span>
        </span>
      ) : null}
    </div>
  );
}

function yesNo(value: boolean): "yes" | "no" {
  return value ? "yes" : "no";
}

function agenticCertificateExpiringSoon(value: string | null | undefined): boolean {
  if (!value) return false;
  const remaining = new Date(value).getTime() - Date.now();
  return Number.isFinite(remaining) && remaining <= 7 * 86_400_000;
}
