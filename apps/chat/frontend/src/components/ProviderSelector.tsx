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

function normalizeProviderQuery(value: string) {
  return value.trim().toLowerCase();
}

function providerSearchText(provider: ProviderItem) {
  return [
    provider.label,
    provider.description,
    provider.provider_id,
    provider.default_model_family,
    provider.hosted_provider_id,
    provider.hosted_model_id,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function providerMatchesQuery(provider: ProviderItem, normalizedQuery: string) {
  return !normalizedQuery || providerSearchText(provider).includes(normalizedQuery);
}

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
  const menuId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const activeIndexRef = useRef(0);
  const suppressNextClickRef = useRef(false);
  const suppressClickResetRef = useRef<number | null>(null);
  const normalizedQuery = normalizeProviderQuery(query);
  const selectedProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;
  const selectedLabel = selectedProvider?.label || "Select model";
  const filteredProviders = useMemo(
    () => providers.filter((provider) => providerMatchesQuery(provider, normalizedQuery)),
    [providers, normalizedQuery],
  );
  const activeProvider = filteredProviders[activeIndex] || filteredProviders[0];
  const activeProviderOptionId = activeProvider ? `${menuId}-option-${activeProvider.provider_id}` : undefined;
  const isDisabled = disabled || !providers.length;

  function selectedProviderIndex(options: ProviderItem[]) {
    const optionIndex = options.findIndex((provider) => provider.provider_id === activeProviderId);
    return optionIndex >= 0 ? optionIndex : 0;
  }

  function openMenu() {
    setQuery("");
    const nextActiveIndex = selectedProviderIndex(providers);
    activeIndexRef.current = nextActiveIndex;
    setActiveIndex(nextActiveIndex);
    setIsOpen(true);
  }

  function closeMenu({ restoreFocus = false }: { restoreFocus?: boolean } = {}) {
    setIsOpen(false);
    setQuery("");
    activeIndexRef.current = 0;
    setActiveIndex(0);
    if (restoreFocus) {
      buttonRef.current?.focus();
    }
  }

  function moveActiveProvider(direction: 1 | -1) {
    const providerCount = filteredProviders.length;
    const nextIndex = providerCount ? (activeIndexRef.current + direction + providerCount) % providerCount : 0;
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
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu({ restoreFocus: true });
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      searchInputRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const nextIndex = Math.min(activeIndexRef.current, Math.max(filteredProviders.length - 1, 0));
    activeIndexRef.current = nextIndex;
    setActiveIndex(nextIndex);
  }, [filteredProviders.length, isOpen]);

  useEffect(() => {
    return () => {
      if (suppressClickResetRef.current !== null) {
        window.clearTimeout(suppressClickResetRef.current);
      }
    };
  }, []);

  function selectProvider(providerId: string) {
    onSelect(providerId);
    closeMenu();
  }

  function handleQueryChange(value: string) {
    const nextNormalizedQuery = normalizeProviderQuery(value);
    const nextFilteredProviders = providers.filter((provider) => providerMatchesQuery(provider, nextNormalizedQuery));
    const nextActiveIndex = selectedProviderIndex(nextFilteredProviders);
    setQuery(value);
    activeIndexRef.current = nextActiveIndex;
    setActiveIndex(nextActiveIndex);
  }

  function selectActiveProvider() {
    const provider = filteredProviders[activeIndexRef.current] || filteredProviders[0];
    if (!provider) {
      return;
    }
    selectProvider(provider.provider_id);
  }

  function handleSearchKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
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
      if (event.nativeEvent.isComposing) {
        return;
      }
      event.preventDefault();
      selectActiveProvider();
    }
  }

  function handleTriggerPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "mouse") {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    suppressNextClickRef.current = true;
    if (suppressClickResetRef.current !== null) {
      window.clearTimeout(suppressClickResetRef.current);
    }
    suppressClickResetRef.current = window.setTimeout(() => {
      suppressNextClickRef.current = false;
      suppressClickResetRef.current = null;
    }, 700);
    if (isOpen) {
      closeMenu();
    } else {
      openMenu();
    }
  }

  function handleTriggerClick() {
    if (suppressNextClickRef.current) {
      suppressNextClickRef.current = false;
      if (suppressClickResetRef.current !== null) {
        window.clearTimeout(suppressClickResetRef.current);
        suppressClickResetRef.current = null;
      }
      return;
    }
    if (isOpen) {
      closeMenu();
    } else {
      openMenu();
    }
  }

  return (
    <div className="chatapp-provider-selector">
      <button
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label={`Model: ${selectedLabel}`}
        className={`chatapp-composer__tool-button chatapp-provider-selector__trigger ${isOpen ? "is-active" : ""}`}
        disabled={isDisabled}
        onClick={handleTriggerClick}
        onPointerDown={handleTriggerPointerDown}
        ref={buttonRef}
        title={`Model: ${selectedLabel}`}
        type="button"
      >
        <span aria-hidden="true" className="chatapp-provider-selector__icon material-symbols-rounded">
          hub
        </span>
        <span className="chatapp-provider-selector__label">{selectedLabel}</span>
      </button>
      {isOpen ? (
        <div
          aria-activedescendant={activeProviderOptionId}
          aria-label="Choose model"
          className="chatapp-provider-menu"
          id={menuId}
          ref={panelRef}
          role="listbox"
        >
          <div className="chatapp-provider-menu__header">Models</div>
          <label className="chatapp-provider-menu__search">
            <span className="chatapp-provider-menu__search-label">Search</span>
            <input
              aria-activedescendant={activeProviderOptionId}
              aria-controls={menuId}
              aria-label="Search models"
              className="chatapp-provider-menu__search-input"
              onChange={(event) => {
                handleQueryChange(event.currentTarget.value);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search models"
              ref={searchInputRef}
              type="search"
              value={query}
            />
          </label>
          {filteredProviders.map((provider, providerIndex) => (
            <button
              aria-selected={provider.provider_id === activeProviderId}
              className={`chatapp-provider-menu__item ${provider.provider_id === activeProviderId ? "is-active" : ""} ${providerIndex === activeIndex ? "is-highlighted" : ""}`}
              id={`${menuId}-option-${provider.provider_id}`}
              key={provider.provider_id}
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
              {provider.description ? <span className="chatapp-provider-menu__description">{provider.description}</span> : null}
            </button>
          ))}
          {!filteredProviders.length ? <div className="chatapp-provider-menu__empty">No matching models</div> : null}
        </div>
      ) : null}
    </div>
  );
}
