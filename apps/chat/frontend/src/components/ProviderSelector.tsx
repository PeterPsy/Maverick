import type { ProviderItem } from "../api/client";

export function ProviderSelector({
  activeProviderId,
  disabled,
  onSelect,
  providers,
}: {
  activeProviderId: string;
  disabled: boolean;
  onSelect: (providerId: string) => void;
  providers: ProviderItem[];
}) {
  return (
    <label className="chatapp-provider-selector" title="Provider runtime">
      <span className="chatapp-provider-selector__control">
        <span aria-hidden="true" className="chatapp-provider-selector__icon material-symbols-rounded">
          hub
        </span>
        <select disabled={disabled} onChange={(event) => onSelect(event.target.value)} value={activeProviderId}>
          {providers.map((provider) => (
            <option key={provider.provider_id} value={provider.provider_id}>
              {provider.label}
            </option>
          ))}
        </select>
        <span aria-hidden="true" className="chatapp-provider-selector__chevron material-symbols-rounded">
          expand_more
        </span>
      </span>
    </label>
  );
}
