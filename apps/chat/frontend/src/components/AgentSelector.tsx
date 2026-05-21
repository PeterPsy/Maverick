import { PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import type { AgentTypeSummary } from "../api/client";

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
  const [isOpen, setIsOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const suppressNextClickRef = useRef(false);
  const suppressClickResetRef = useRef<number | null>(null);
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentTypeId) || null;
  const label = selectedAgent?.name || "Default Chat";
  const isDisabled = disabled || locked;

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || panelRef.current?.contains(target) || buttonRef.current?.contains(target)) {
        return;
      }
      setIsOpen(false);
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        buttonRef.current?.focus();
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
    return () => {
      if (suppressClickResetRef.current !== null) {
        window.clearTimeout(suppressClickResetRef.current);
      }
    };
  }, []);

  function selectAgent(agentTypeId: string) {
    onSelect(agentTypeId);
    setIsOpen(false);
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
    setIsOpen((current) => !current);
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
    setIsOpen((current) => !current);
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
        <div aria-label="Choose agent runner" className="chatapp-agent-menu" ref={panelRef} role="listbox">
          <button
            aria-selected={!selectedAgentTypeId}
            className={`chatapp-agent-menu__item ${!selectedAgentTypeId ? "is-active" : ""}`}
            onClick={() => {
              selectAgent("");
            }}
            role="option"
            type="button"
          >
            <span className="chatapp-agent-menu__name">Default Chat</span>
            <span className="chatapp-agent-menu__description">Use the standard Chat runtime prompt.</span>
          </button>
          {agents.map((agent) => (
            <button
              aria-selected={agent.id === selectedAgentTypeId}
              className={`chatapp-agent-menu__item ${agent.id === selectedAgentTypeId ? "is-active" : ""}`}
              key={agent.id}
              onClick={() => {
                selectAgent(agent.id);
              }}
              role="option"
              type="button"
            >
              <span className="chatapp-agent-menu__name">{agent.name}</span>
              {agent.description ? <span className="chatapp-agent-menu__description">{agent.description}</span> : null}
            </button>
          ))}
          {!agents.length ? <div className="chatapp-agent-menu__empty">No agent catalog available</div> : null}
        </div>
      ) : null}
    </div>
  );
}
