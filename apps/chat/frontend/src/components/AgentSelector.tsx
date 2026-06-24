import {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type { AgentTypeSummary } from "../api/client";

type AgentMenuOption =
  | {
      agentTypeId: "";
      description: string;
      key: "default";
      label: string;
    }
  | {
      agentTypeId: string;
      description: string;
      key: string;
      label: string;
    };

const defaultAgentOption: AgentMenuOption = {
  agentTypeId: "",
  description: "Use the standard Chat runtime prompt.",
  key: "default",
  label: "Default Chat",
};

function normalizeAgentQuery(value: string) {
  return value.trim().toLowerCase();
}

function normalizedAgentSearchText(agent: AgentTypeSummary) {
  return [agent.name, agent.description, agent.role_id].join(" ").toLowerCase();
}

function agentMatchesQuery(agent: AgentTypeSummary, normalizedQuery: string) {
  return !normalizedQuery || normalizedAgentSearchText(agent).includes(normalizedQuery);
}

function agentToMenuOption(agent: AgentTypeSummary): AgentMenuOption {
  return {
    agentTypeId: agent.id,
    description: agent.description,
    key: agent.id,
    label: agent.name,
  };
}

function buildMenuOptions(agents: AgentTypeSummary[]) {
  return [defaultAgentOption, ...agents.map(agentToMenuOption)];
}

export function AgentSelector({
  agents,
  disabled,
  locked,
  onSelect,
  selectedAgentTypeId,
}: {
  agents: AgentTypeSummary[];
  disabled: boolean;
  locked: boolean;
  onSelect: (agentTypeId: string) => void;
  selectedAgentTypeId: string;
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
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentTypeId) || null;
  const label = selectedAgent?.name || "Default Chat";
  const isDisabled = disabled || locked;
  const normalizedQuery = normalizeAgentQuery(query);
  const filteredAgents = useMemo(
    () => agents.filter((agent) => agentMatchesQuery(agent, normalizedQuery)),
    [agents, normalizedQuery],
  );
  const menuOptions = useMemo(() => buildMenuOptions(filteredAgents), [filteredAgents]);
  const activeOption = menuOptions[activeIndex] || menuOptions[0];
  const activeOptionId = activeOption ? `${menuId}-option-${activeOption.key}` : undefined;

  function selectedOptionIndex(options: AgentMenuOption[]) {
    if (!selectedAgentTypeId) {
      return 0;
    }
    const optionIndex = options.findIndex((option) => option.agentTypeId === selectedAgentTypeId);
    return optionIndex >= 0 ? optionIndex : 0;
  }

  function openMenu() {
    const unfilteredOptions = buildMenuOptions(agents);
    setQuery("");
    const nextActiveIndex = selectedOptionIndex(unfilteredOptions);
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

  function moveActiveOption(direction: 1 | -1) {
    const optionCount = menuOptions.length;
    const nextIndex = optionCount ? (activeIndexRef.current + direction + optionCount) % optionCount : 0;
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
    const nextIndex = Math.min(activeIndexRef.current, Math.max(menuOptions.length - 1, 0));
    activeIndexRef.current = nextIndex;
    setActiveIndex(nextIndex);
  }, [isOpen, menuOptions.length]);

  useEffect(() => {
    return () => {
      if (suppressClickResetRef.current !== null) {
        window.clearTimeout(suppressClickResetRef.current);
      }
    };
  }, []);

  function selectAgent(agentTypeId: string) {
    onSelect(agentTypeId);
    closeMenu();
  }

  function handleQueryChange(value: string) {
    const nextNormalizedQuery = normalizeAgentQuery(value);
    const nextFilteredAgents = agents.filter((agent) => agentMatchesQuery(agent, nextNormalizedQuery));
    const nextOptions = buildMenuOptions(nextFilteredAgents);
    const nextActiveIndex = selectedOptionIndex(nextOptions);
    setQuery(value);
    activeIndexRef.current = nextActiveIndex;
    setActiveIndex(nextActiveIndex);
  }

  function selectActiveOption() {
    const option = menuOptions[activeIndexRef.current] || menuOptions[0];
    if (!option) {
      return;
    }
    selectAgent(option.agentTypeId);
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
      moveActiveOption(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActiveOption(-1);
      return;
    }
    if (event.key === "Enter") {
      if (event.nativeEvent.isComposing) {
        return;
      }
      event.preventDefault();
      selectActiveOption();
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
    <div className="chatapp-agent-selector">
      <button
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-label={`Agent runner: ${label}`}
        className={`chatapp-composer__tool-button chatapp-agent-selector__trigger ${selectedAgentTypeId || isOpen ? "is-active" : ""}`}
        disabled={isDisabled}
        onClick={handleTriggerClick}
        onPointerDown={handleTriggerPointerDown}
        ref={buttonRef}
        title={locked ? "This chat is already running with its selected agent" : `Agent runner: ${label}`}
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          smart_toy
        </span>
      </button>
      {isOpen ? (
        <div
          aria-activedescendant={activeOptionId}
          aria-label="Choose agent runner"
          className="chatapp-agent-menu"
          id={menuId}
          ref={panelRef}
          role="listbox"
        >
          <label className="chatapp-agent-menu__search">
            <input
              aria-activedescendant={activeOptionId}
              aria-controls={menuId}
              aria-label="Search agents"
              className="chatapp-agent-menu__search-input"
              onChange={(event) => {
                handleQueryChange(event.currentTarget.value);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search agents"
              ref={searchInputRef}
              type="search"
              value={query}
            />
          </label>
          {menuOptions.map((option, optionIndex) => (
            <button
              aria-selected={option.agentTypeId === selectedAgentTypeId}
              className={`chatapp-agent-menu__item ${option.agentTypeId === selectedAgentTypeId ? "is-active" : ""} ${optionIndex === activeIndex ? "is-highlighted" : ""}`}
              data-agent-option-index={optionIndex}
              id={`${menuId}-option-${option.key}`}
              key={option.key}
              onClick={() => {
                selectAgent(option.agentTypeId);
              }}
              onMouseEnter={() => {
                activeIndexRef.current = optionIndex;
                setActiveIndex(optionIndex);
              }}
              role="option"
              type="button"
            >
              <span className="chatapp-agent-menu__name">{option.label}</span>
              {option.description ? <span className="chatapp-agent-menu__description">{option.description}</span> : null}
            </button>
          ))}
          {!agents.length ? <div className="chatapp-agent-menu__empty">No agent catalog available</div> : null}
          {agents.length && !filteredAgents.length ? <div className="chatapp-agent-menu__empty">No matching agents</div> : null}
        </div>
      ) : null}
    </div>
  );
}
