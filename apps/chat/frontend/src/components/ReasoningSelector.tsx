import type { ProviderReasoningOption } from "../api/client";

export function ReasoningSelector({
  disabled,
  onChange,
  options,
  value,
}: {
  disabled: boolean;
  onChange: (effort: string) => void;
  options: ProviderReasoningOption[];
  value: string;
}) {
  if (!options.length) return null;
  return (
    <label className="chatapp-reasoning-selector" title="Reasoning effort for this new chat">
      <span aria-hidden="true" className="material-symbols-rounded">psychology</span>
      <select
        aria-label="Reasoning effort"
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
        value={value || options[0]?.effort || ""}
      >
        {options.map((option) => (
          <option key={option.effort} value={option.effort}>
            {option.label || option.effort}
          </option>
        ))}
      </select>
    </label>
  );
}
