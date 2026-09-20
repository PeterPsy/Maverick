import {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ProviderItem } from "../api/client";
import {
  orderedExecutionFamilies,
  safeProviderExecutionFamily,
} from "../lib/executionFamilies";

function providerIsSelectable(provider: ProviderItem) {
  return provider.selectable !== false && provider.status === "active";
}

export function ProviderSelector({
  activeProviderId,
  disabled,
  locked = false,
  onReasoningEffortChange = () => undefined,
  onSelect,
  providers,
  reasoningEffort = "",
}: {
  activeProviderId: string;
  disabled: boolean;
  locked?: boolean;
  onReasoningEffortChange?: (effort: string) => void;
  onSelect: (providerId: string, reasoningEffort?: string) => void;
  providers: ProviderItem[];
  reasoningEffort?: string;
}) {
  const menuId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const activeIndexRef = useRef(0);
  const selectableProviders = useMemo(
    () => providers.filter(providerIsSelectable),
    [providers],
  );
  const executionFamilies = useMemo(
    () => orderedExecutionFamilies(selectableProviders),
    [selectableProviders],
  );
  const selectedProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
  const selectedLabel = selectedProvider?.label || "Select model";
  const selectedReasoningEffort = selectedProvider
    ? reasoningEffort
      || selectedProvider.default_reasoning_effort
      || selectedProvider.supported_reasoning_efforts?.[0]?.effort
      || ""
    : "";
  const selectedReasoningLabel = selectedProvider?.supported_reasoning_efforts
    ?.find((option) => option.effort === selectedReasoningEffort)?.label
    || selectedReasoningEffort;
  const selectedDisplayLabel = selectedReasoningLabel
    ? `${selectedLabel} · ${selectedReasoningLabel}`
    : selectedLabel;
  const activeProvider = selectableProviders[activeIndex] || selectableProviders[0];
  const activeProviderOptionId = activeProvider ? `${menuId}-option-${activeProvider.provider_id}` : undefined;
  const isDisabled = disabled || locked || !selectableProviders.length;

  function selectedProviderIndex() {
    const optionIndex = selectableProviders.findIndex(
      (provider) => provider.provider_id === activeProviderId,
    );
    return optionIndex >= 0 ? optionIndex : 0;
  }

  function openMenu() {
    const nextActiveIndex = selectedProviderIndex();
    activeIndexRef.current = nextActiveIndex;
    setActiveIndex(nextActiveIndex);
    setIsOpen(true);
  }

  function closeMenu({ restoreFocus = false }: { restoreFocus?: boolean } = {}) {
    setIsOpen(false);
    activeIndexRef.current = 0;
    setActiveIndex(0);
    if (restoreFocus) {
      buttonRef.current?.focus();
    }
  }

  function moveActiveProvider(direction: 1 | -1) {
    const providerCount = selectableProviders.length;
    const nextIndex = providerCount
      ? (activeIndexRef.current + direction + providerCount) % providerCount
      : 0;
    activeIndexRef.current = nextIndex;
    setActiveIndex(nextIndex);
  }

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || panelRef.current?.contains(target) || buttonRef.current?.contains(target)) {
        return;
      }
      closeMenu();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      panelRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const nextIndex = Math.min(
      activeIndexRef.current,
      Math.max(selectableProviders.length - 1, 0),
    );
    activeIndexRef.current = nextIndex;
    setActiveIndex(nextIndex);
  }, [selectableProviders.length, isOpen]);

  function selectProvider(providerId: string) {
    const provider = selectableProviders.find((candidate) => candidate.provider_id === providerId);
    if (!provider) {
      return;
    }
    onSelect(providerId);
    closeMenu();
  }

  function selectProviderReasoning(provider: ProviderItem, effort: string) {
    if (provider.provider_id !== activeProviderId) {
      onSelect(provider.provider_id, effort);
      return;
    }
    onReasoningEffortChange(effort);
  }

  function selectActiveProvider() {
    const provider = selectableProviders[activeIndexRef.current] || selectableProviders[0];
    if (provider) {
      selectProvider(provider.provider_id);
    }
  }

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu({ restoreFocus: true });
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActiveProvider(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActiveProvider(-1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      selectActiveProvider();
    }
  }

  function handleTriggerPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "mouse") {
      return;
    }
    event.preventDefault();
  }

  return (
    <div className="chatapp-provider-selector">
      <button
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label={`Model: ${selectedDisplayLabel}`}
        className={`chatapp-composer__tool-button chatapp-provider-selector__trigger ${isOpen ? "is-active" : ""}`}
        disabled={isDisabled}
        onClick={() => {
          if (isOpen) closeMenu();
          else openMenu();
        }}
        onPointerDown={handleTriggerPointerDown}
        ref={buttonRef}
        title={locked
          ? `${selectedDisplayLabel}. Start a new chat to change model or reasoning.`
          : `Model: ${selectedDisplayLabel}`}
        type="button"
      >
        <span aria-hidden="true" className="chatapp-provider-selector__icon material-symbols-rounded">
          hub
        </span>
        <span className="chatapp-provider-selector__label">{selectedDisplayLabel}</span>
      </button>
      {isOpen ? (
        <div
          aria-activedescendant={activeProviderOptionId}
          aria-label="Choose model"
          className="chatapp-provider-menu"
          id={menuId}
          onKeyDown={handleMenuKeyDown}
          ref={panelRef}
          role="listbox"
          tabIndex={-1}
        >
          {executionFamilies.map((family) => {
            const familyProviders = selectableProviders.filter(
              (provider) => safeProviderExecutionFamily(provider) === family.family_id,
            );
            if (!familyProviders.length) {
              return null;
            }
            return (
              <section className="chatapp-provider-menu__family" data-execution-family={family.family_id} key={family.family_id}>
                <header className="chatapp-provider-menu__family-heading">
                  <span>{family.label}</span>
                </header>
                {familyProviders.map((provider) => {
                  const providerIndex = selectableProviders.findIndex(
                    (candidate) => candidate.provider_id === provider.provider_id,
                  );
                  return (
                    <div className="chatapp-provider-menu__option-block" key={provider.provider_id}>
                      <button
                        aria-selected={provider.provider_id === activeProviderId}
                        className={`chatapp-provider-menu__item ${provider.provider_id === activeProviderId ? "is-active" : ""} ${providerIndex === activeIndex ? "is-highlighted" : ""}`}
                        id={`${menuId}-option-${provider.provider_id}`}
                        onClick={() => {
                          selectProvider(provider.provider_id);
                        }}
                        onMouseEnter={() => {
                          activeIndexRef.current = providerIndex;
                          setActiveIndex(providerIndex);
                        }}
                        role="option"
                        type="button"
                      >
                        <span className="chatapp-provider-menu__name">{provider.label}</span>
                      </button>
                      {provider.supported_reasoning_efforts?.length ? (
                        <label className="chatapp-provider-menu__reasoning">
                          <span className="chatapp-provider-menu__reasoning-label">Reasoning</span>
                          <select
                            aria-label={`Reasoning for ${provider.label}`}
                            disabled={disabled || locked}
                            onChange={(event) => selectProviderReasoning(provider, event.currentTarget.value)}
                            onKeyDown={(event) => event.stopPropagation()}
                            value={provider.provider_id === activeProviderId
                              ? reasoningEffort || provider.default_reasoning_effort || provider.supported_reasoning_efforts[0]?.effort || ""
                              : provider.default_reasoning_effort || provider.supported_reasoning_efforts[0]?.effort || ""}
                          >
                            {provider.supported_reasoning_efforts.map((option) => (
                              <option key={option.effort} value={option.effort}>{option.label || option.effort}</option>
                            ))}
                          </select>
                        </label>
                      ) : null}
                    </div>
                  );
                })}
              </section>
            );
          })}
          {!selectableProviders.length ? <div className="chatapp-provider-menu__empty">No models available</div> : null}
        </div>
      ) : null}
    </div>
  );
}
