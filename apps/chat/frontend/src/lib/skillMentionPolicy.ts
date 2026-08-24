import type { ProviderItem } from "../api/client";
import { providerUsesPlainHostedRuntime } from "./providerRuntimeOptions";

export function skillIdsVisibleInComposer({
  activationMode,
  allowedSkillIds,
  availableSkillIds,
  provider,
  sourceAppId = "",
  sourceAppSupportsSkillInvocations = false,
}: {
  activationMode?: string;
  allowedSkillIds?: string[];
  availableSkillIds: string[];
  provider: ProviderItem | null;
  sourceAppId?: string;
  sourceAppSupportsSkillInvocations?: boolean;
}): string[] {
  if (
    activationMode !== "explicit"
    || !provider
    || providerUsesPlainHostedRuntime(provider)
    || provider.capabilities?.supports_skills !== true
    || (sourceAppId && !sourceAppSupportsSkillInvocations)
  ) {
    return [];
  }
  if (!allowedSkillIds?.length) {
    return availableSkillIds;
  }
  const allowed = new Set(allowedSkillIds);
  return availableSkillIds.filter((skillId) => allowed.has(skillId));
}
