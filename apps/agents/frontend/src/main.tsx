import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/main.css';

type Role = {
  id: string;
  name: string;
  description: string;
  instructions: string;
};

type AgentType = {
  id: string;
  name: string;
  description: string;
  role_id: string;
  codex_skill_ids: string[];
  execution_mode_policy: string;
  default_execution_mode: string;
  trace_verbosity: string;
  enabled: boolean;
};

type Instance = {
  id: string;
  name: string;
  agent_type_id: string;
  status: string;
  runtime_session_id: string | null;
};

type Catalog = {
  common_prompt: string;
  roles: Role[];
  agent_types: AgentType[];
  instances: Instance[];
};

type Preview = {
  rendered: string;
};

const emptyCatalog: Catalog = { common_prompt: '', roles: [], agent_types: [], instances: [] };

async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/agents/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Agents request failed');
  }
  return payload as T;
}

function App() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState('');
  const [query, setQuery] = useState('');
  const [preview, setPreview] = useState('');
  const [error, setError] = useState('');
  const [runtimeSessionId, setRuntimeSessionId] = useState('');
  const [savingPrompt, setSavingPrompt] = useState(false);

  async function refresh() {
    const next = await callBackend<Catalog>({ action: 'catalog' });
    setCatalog(next);
    setSelectedAgentTypeId((current) => current || next.agent_types[0]?.id || '');
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedAgentTypeId) {
      setPreview('');
      return;
    }
    callBackend<Preview>({ action: 'preview_prompt', agent_type_id: selectedAgentTypeId })
      .then((payload) => setPreview(payload.rendered))
      .catch((err: Error) => setError(err.message));
  }, [selectedAgentTypeId]);

  const filteredAgentTypes = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return catalog.agent_types;
    return catalog.agent_types.filter((item) => {
      return `${item.name} ${item.description} ${item.role_id}`.toLowerCase().includes(needle);
    });
  }, [catalog.agent_types, query]);

  const selectedAgentType = catalog.agent_types.find((item) => item.id === selectedAgentTypeId);
  const selectedRole = catalog.roles.find((role) => role.id === selectedAgentType?.role_id);

  async function saveCommonPrompt() {
    setSavingPrompt(true);
    setError('');
    try {
      const prompt = (document.getElementById('common-prompt') as HTMLTextAreaElement | null)?.value || '';
      await callBackend({ action: 'set_common_prompt', prompt });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingPrompt(false);
    }
  }

  async function saveAgentType() {
    if (!selectedAgentType) return;
    setError('');
    try {
      const name = (document.getElementById('agent-type-name') as HTMLInputElement | null)?.value || selectedAgentType.name;
      const description =
        (document.getElementById('agent-type-description') as HTMLTextAreaElement | null)?.value || selectedAgentType.description;
      await callBackend({
        action: 'update_agent_type',
        id: selectedAgentType.id,
        role_id: selectedAgentType.role_id,
        name,
        description,
        codex_skill_ids: selectedAgentType.codex_skill_ids,
        execution_mode_policy: selectedAgentType.execution_mode_policy,
        default_execution_mode: selectedAgentType.default_execution_mode,
        trace_verbosity: selectedAgentType.trace_verbosity,
        enabled: selectedAgentType.enabled
      });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function saveRole() {
    if (!selectedRole) return;
    setError('');
    try {
      const instructions =
        (document.getElementById('role-instructions') as HTMLTextAreaElement | null)?.value || selectedRole.instructions;
      await callBackend({
        action: 'update_role',
        id: selectedRole.id,
        name: selectedRole.name,
        description: selectedRole.description,
        instructions
      });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function createInstance() {
    if (!selectedAgentType) return;
    setError('');
    try {
      await callBackend({ action: 'create_instance', agent_type_id: selectedAgentType.id, name: selectedAgentType.name });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function startRuntimeSession() {
    if (!selectedAgentType) return;
    setError('');
    try {
      const response = await fetch('/api/runtime/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: selectedAgentType.id,
          requested_mode: selectedAgentType.default_execution_mode,
          system_prompt: preview,
          skill_ids: selectedAgentType.codex_skill_ids,
          source_app_id: 'agents'
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || 'Runtime session failed');
      }
      setRuntimeSessionId(payload.session_id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="agents-shell">
      <section className="agents-sidebar">
        <div className="agents-titlebar">
          <h1>Agents</h1>
          <span>{catalog.agent_types.length}</span>
        </div>
        <input
          className="agents-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search agents"
          aria-label="Search agents"
        />
        <div className="agents-list">
          {filteredAgentTypes.map((agentType) => (
            <button
              key={agentType.id}
              className={agentType.id === selectedAgentTypeId ? 'agent-row selected' : 'agent-row'}
              onClick={() => setSelectedAgentTypeId(agentType.id)}
            >
              <strong>{agentType.name}</strong>
              <span>{agentType.role_id}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="agents-detail">
        {error ? <div className="agents-error">{error}</div> : null}
        {selectedAgentType && selectedRole ? (
          <>
            <header className="detail-header">
              <div>
                <h2>{selectedAgentType.name}</h2>
                <p>{selectedAgentType.description}</p>
              </div>
              <div className="action-group">
                <button className="secondary-action" onClick={createInstance}>Create Instance</button>
                <button className="primary-action" onClick={startRuntimeSession}>Use In Runtime</button>
              </div>
            </header>
            {runtimeSessionId ? <div className="runtime-banner">Runtime session: {runtimeSessionId}</div> : null}

            <div className="meta-grid">
              <div><span>Role</span><strong>{selectedRole.name}</strong></div>
              <div><span>Mode</span><strong>{selectedAgentType.default_execution_mode}</strong></div>
              <div><span>Policy</span><strong>{selectedAgentType.execution_mode_policy}</strong></div>
              <div><span>Trace</span><strong>{selectedAgentType.trace_verbosity}</strong></div>
            </div>

            <section className="editor-band">
              <div className="band-heading">
                <h3>Agent Type</h3>
                <button onClick={saveAgentType}>Save</button>
              </div>
              <input id="agent-type-name" key={`${selectedAgentType.id}-name`} defaultValue={selectedAgentType.name} />
              <textarea
                id="agent-type-description"
                key={`${selectedAgentType.id}-description`}
                defaultValue={selectedAgentType.description}
              />
            </section>

            <section className="editor-band">
              <div className="band-heading">
                <h3>Role Instructions</h3>
                <button onClick={saveRole}>Save</button>
              </div>
              <textarea id="role-instructions" key={selectedRole.id} defaultValue={selectedRole.instructions} />
            </section>

            <section className="editor-band">
              <div className="band-heading">
                <h3>Common Prompt</h3>
                <button onClick={saveCommonPrompt} disabled={savingPrompt}>{savingPrompt ? 'Saving' : 'Save'}</button>
              </div>
              <textarea id="common-prompt" defaultValue={catalog.common_prompt} />
            </section>

            <section className="editor-band">
              <h3>Prompt Preview</h3>
              <pre>{preview}</pre>
            </section>

            <section className="editor-band">
              <h3>Instances</h3>
              <div className="instance-list">
                {catalog.instances.length ? catalog.instances.map((instance) => (
                  <div className="instance-row" key={instance.id}>
                    <strong>{instance.name}</strong>
                    <span>{instance.status}</span>
                  </div>
                )) : <p>No instances yet.</p>}
              </div>
            </section>
          </>
        ) : (
          <div className="empty-state">No agent type selected.</div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(<App />);
