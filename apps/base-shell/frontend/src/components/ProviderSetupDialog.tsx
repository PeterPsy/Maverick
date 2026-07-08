import { useEffect, useMemo, useState } from "react";
import { ProviderItem, ProviderSetupSettings } from "../api";
import { Button, Dialog, Surface } from "../ui";
import { defaultReasoningForOption, usableModelOptions, withReasoningFallback } from "./providerModelOptions";

type ProviderSetupPayload = {
  provider_id: string;
  model_id?: string | null;
  model_reasoning_effort?: string | null;
};

export type ProviderSetupDraft = {
  providerId: string;
  modelId: string;
  reasoningEffort: string;
};

function selectedProvider(providers: ProviderItem[], preferredProviderId?: string): ProviderItem | null {
  return (
    providers.find((provider) => provider.provider_id === preferredProviderId) ||
    providers.find((provider) => provider.provider_id === "codex") ||
    providers[0] ||
    null
  );
}

export function buildProviderSetupDraft(
  settings: ProviderSetupSettings | null,
  previous: Partial<ProviderSetupDraft> = {},
): ProviderSetupDraft {
  const providers = settings?.provider.available_providers || [];
  const provider = selectedProvider(providers, previous.providerId);
  const modelOptions = usableModelOptions(provider?.model_options).map(withReasoningFallback);
  const previousModelStillValid = modelOptions.some((option) => option.model_id === previous.modelId);
  const defaultModelStillValid = modelOptions.some((option) => option.model_id === provider?.default_model_family);
  const modelId = previousModelStillValid
    ? previous.modelId || ""
    : defaultModelStillValid
      ? provider?.default_model_family || ""
      : modelOptions[0]?.model_id || provider?.default_model_family || "";
  const modelOption = modelOptions.find((option) => option.model_id === modelId) || modelOptions[0] || null;
  const previousReasoningStillValid = modelOption?.supported_reasoning_efforts.some((option) => option.effort === previous.reasoningEffort);

  return {
    providerId: provider?.provider_id || "",
    modelId,
    reasoningEffort: previousReasoningStillValid ? previous.reasoningEffort || "" : defaultReasoningForOption(modelOption),
  };
}

export function ProviderSetupDialog({
  onClose,
  onConfigure,
  open,
  settings,
}: {
  onClose: () => void;
  onConfigure: (payload: ProviderSetupPayload) => Promise<void>;
  open: boolean;
  settings: ProviderSetupSettings | null;
}) {
  const providers = settings?.provider.available_providers || [];
  const [draft, setDraft] = useState<ProviderSetupDraft>(() => buildProviderSetupDraft(settings));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft((current) => buildProviderSetupDraft(settings, current));
    setError(null);
  }, [settings]);

  const provider = useMemo(() => selectedProvider(providers, draft.providerId), [draft.providerId, providers]);
  const modelOptions = useMemo(() => usableModelOptions(provider?.model_options).map(withReasoningFallback), [provider]);
  const selectedModelOption = modelOptions.find((option) => option.model_id === draft.modelId) || modelOptions[0] || null;
  const reasoningOptions = selectedModelOption?.supported_reasoning_efforts || [];
  const isDismissible = settings?.user.platform_role !== "admin" || providers.length === 0;
  const canSubmit = !!draft.providerId && !isSaving;

  function updateProvider(providerId: string) {
    setDraft(buildProviderSetupDraft(settings, { providerId }));
  }

  function updateModel(modelId: string) {
    const option = modelOptions.find((item) => item.model_id === modelId) || null;
    setDraft((current) => ({
      ...current,
      modelId,
      reasoningEffort: defaultReasoningForOption(option),
    }));
  }

  async function submitProviderSetup() {
    if (!canSubmit) {
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      await onConfigure({
        provider_id: draft.providerId,
        model_id: draft.modelId || null,
        model_reasoning_effort: draft.reasoningEffort || null,
      });
    } catch (setupError) {
      setError(setupError instanceof Error ? setupError.message : "Impossibile configurare il provider.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Dialog
      description="Scegli il backend AI del workspace prima di usare Chat o gli agenti."
      dismissible={isDismissible}
      onClose={onClose}
      open={open}
      panelClassName="bs-provider-setup-dialog"
      title="Configura provider AI"
    >
      <div className="bs-provider-setup">
        <Surface className="bs-provider-setup__provider">
          <label className="bs-settings-field">
            <span>Provider</span>
            <select disabled={!providers.length || isSaving} onChange={(event) => updateProvider(event.target.value)} value={draft.providerId}>
              {providers.length ? null : <option value="">Nessun provider disponibile</option>}
              {providers.map((item) => (
                <option key={item.provider_id} value={item.provider_id}>
                  {item.label || item.provider_id}
                </option>
              ))}
            </select>
          </label>
          <p className="bs-dialog-card__copy">
            {provider?.description || "Il provider selezionato gestisce le nuove sessioni runtime di questo workspace."}
          </p>
        </Surface>
        <div className="bs-provider-setup__grid">
          <label className="bs-settings-field">
            <span>Modello</span>
            <select disabled={!modelOptions.length || isSaving} onChange={(event) => updateModel(event.target.value)} value={draft.modelId}>
              {modelOptions.length ? null : <option value="">Default provider</option>}
              {modelOptions.map((option) => (
                <option key={option.model_id} value={option.model_id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="bs-settings-field">
            <span>Reasoning</span>
            <select
              disabled={!reasoningOptions.length || isSaving}
              onChange={(event) => setDraft((current) => ({ ...current, reasoningEffort: event.target.value }))}
              value={draft.reasoningEffort}
            >
              {reasoningOptions.length ? null : <option value="">Default</option>}
              {reasoningOptions.map((option) => (
                <option key={option.effort} value={option.effort}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {settings?.provider.blocked_reason ? (
          <p className="bs-provider-setup__status">Stato provider: {settings.provider.blocked_reason.replaceAll("_", " ")}</p>
        ) : null}
        {error ? <p className="bs-settings-provider-error">{error}</p> : null}
        <Button disabled={!canSubmit} loading={isSaving} onClick={submitProviderSetup} variant="primary">
          Attiva provider
        </Button>
      </div>
    </Dialog>
  );
}
