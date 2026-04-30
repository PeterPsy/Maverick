import type { AgentType, Catalog } from '../types';

type AgentsSidebarProps = {
  catalog: Catalog;
  query: string;
  selectedAgentTypeId: string;
  filteredAgentTypes: AgentType[];
  onCreate: () => void;
  onSetQuery: (query: string) => void;
  onSelectAgentType: (agentTypeId: string) => void;
};

export function AgentsSidebar({
  catalog,
  query,
  selectedAgentTypeId,
  filteredAgentTypes,
  onCreate,
  onSetQuery,
  onSelectAgentType
}: AgentsSidebarProps) {
  return (
    <section className="agents-sidebar">
      <div className="agents-titlebar">
        <div>
          <p className="agents-eyebrow">Maverick</p>
          <h1>Agents</h1>
        </div>
        <div className="agents-titlebar-actions">
          <span>{catalog.agent_types.length}</span>
          <button className="agents-new-button" onClick={onCreate} type="button" aria-label="Create agent">
            <span className="material-symbols-rounded" aria-hidden="true">add</span>
          </button>
        </div>
      </div>

      <input
        className="agents-search"
        value={query}
        onChange={(event) => onSetQuery(event.target.value)}
        placeholder="Search agents"
        aria-label="Search agents"
      />
      <div className="agents-list">
        {filteredAgentTypes.map((agentType) => (
          <button
            key={agentType.id}
            className={agentType.id === selectedAgentTypeId ? 'agent-row selected' : 'agent-row'}
            onClick={() => onSelectAgentType(agentType.id)}
          >
            <span className="agent-row-icon material-symbols-rounded" aria-hidden="true">smart_toy</span>
            <span className="agent-row-copy">
              <strong>{agentType.name}</strong>
              <span>{agentType.role_id}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
