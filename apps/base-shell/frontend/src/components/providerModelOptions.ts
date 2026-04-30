import { ProviderModelOption, ProviderReasoningOption } from "../api";

export const FALLBACK_REASONING_OPTIONS: ProviderReasoningOption[] = [
  { effort: "low", label: "Low", description: "Fast responses with lighter reasoning" },
  { effort: "medium", label: "Mid", description: "Balanced reasoning depth" },
  { effort: "high", label: "High", description: "Greater reasoning depth" },
  { effort: "xhigh", label: "Extra high", description: "Maximum reasoning depth" },
];

export function usableModelOptions(options: ProviderModelOption[] | null | undefined): ProviderModelOption[] {
  return Array.isArray(options) ? options.filter((option) => !!option?.model_id) : [];
}

export function defaultReasoningForOption(option: ProviderModelOption | null): string {
  if (!option) {
    return "";
  }
  if (option.default_reasoning_effort) {
    return option.default_reasoning_effort;
  }
  return option.supported_reasoning_efforts[0]?.effort || "";
}

export function withReasoningFallback(option: ProviderModelOption): ProviderModelOption {
  if (option.supported_reasoning_efforts.length) {
    return option;
  }
  return {
    ...option,
    default_reasoning_effort: option.default_reasoning_effort || "medium",
    supported_reasoning_efforts: FALLBACK_REASONING_OPTIONS,
  };
}

export function fallbackModelOption(modelId: string, reasoningEffort: string): ProviderModelOption {
  return {
    model_id: modelId,
    label: modelId,
    description: "Workspace-selected Codex model.",
    default_reasoning_effort: reasoningEffort || "medium",
    supported_reasoning_efforts: FALLBACK_REASONING_OPTIONS,
  };
}
