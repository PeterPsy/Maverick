import { useEffect, useRef, useState } from 'react';
import { callBackend, callProviderBackend, getAppDependencies } from './api';
import { AgentsDetail } from './components/AgentsDetail';
import { DeleteAgentTypeDialog } from './components/DeleteAgentTypeDialog';
import { NewAgentModal } from './components/NewAgentModal';
import { agentTypeIdFromParams, scalarString, shouldOpenNewAgent } from './lib/agentNavigationParams';
import { notifyActiveAgentSelection } from './lib/activeAgentSelection';
import { selectedProviderAppId, skillIdsForAgentSave } from './lib/dependencies';
import type { AgentEdits, AppDependenciesPayload, Catalog, SkillSummary } from './types';

const emptyCatalog: Catalog = { agent_types: [] };

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'custom-agent';
}

function initialAgentTypeId() {
  return new URLSearchParams(window.location.search).get('agent_type_id') || '';
}

function nextSelection(catalog: Catalog, current: string, preferred?: string) {
  for (const candidate of [preferred, current]) {
    if (candidate && catalog.agent_types.some((item) => item.id === candidate)) return candidate;
  }
  return catalog.agent_types[0]?.id || '';
}

export function App() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState('');
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [skillProviderAppId, setSkillProviderAppId] = useState('');
  const [error, setError] = useState('');
  const [isCatalogLoading, setIsCatalogLoading] = useState(true);
  const [savingEdits, setSavingEdits] = useState(false);
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [newAgentModalOpen, setNewAgentModalOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [deletingAgent, setDeletingAgent] = useState(false);
  const selectedIdRef = useRef('');
  const consumedNewAgentRequests = useRef<Set<string>>(new Set());
  const consumedLegacyRequest = useRef(false);

  async function loadSkillCatalog(dependencies?: AppDependenciesPayload) {
    const resolved = dependencies || await getAppDependencies('agents');
    const providerAppId = selectedProviderAppId(resolved);
    if (!providerAppId) return { providerAppId: '', skills: [] };
    const payload = await callProviderBackend<{ skills: SkillSummary[] }>(providerAppId, { action: 'catalog' });
    return { providerAppId, skills: payload.skills.filter((skill) => skill.enabled) };
  }

  async function refresh(preferred?: string) {
    setIsCatalogLoading(true);
    try {
      const [nextCatalog, skillCatalog] = await Promise.all([
        callBackend<Catalog>({ action: 'catalog' }),
        loadSkillCatalog()
      ]);
      const selected = nextSelection(nextCatalog, selectedIdRef.current, preferred);
      setCatalog(nextCatalog);
      setSkills(skillCatalog.skills);
      setSkillProviderAppId(skillCatalog.providerAppId);
      setSelectedAgentTypeId(selected);
      selectedIdRef.current = selected;
    } finally {
      setIsCatalogLoading(false);
    }
  }

  async function refreshSkills(dependencies?: AppDependenciesPayload) {
    const next = await loadSkillCatalog(dependencies);
    setSkills(next.skills);
    setSkillProviderAppId(next.providerAppId);
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedId = agentTypeIdFromParams(params);
    if (requestedId) {
      if (catalog.agent_types.some((item) => item.id === requestedId)) setSelectedAgentTypeId(requestedId);
      else await refresh(requestedId);
    }
    if (!shouldOpenNewAgent(params)) return;
    const requestId = scalarString(params.new_agent_request_id);
    if (requestId) {
      if (consumedNewAgentRequests.current.has(requestId)) return;
      consumedNewAgentRequests.current.add(requestId);
    } else if (consumedLegacyRequest.current) {
      return;
    } else {
      consumedLegacyRequest.current = true;
    }
    setNewAgentModalOpen(true);
  }

  useEffect(() => {
    void refresh(initialAgentTypeId()).catch((caught: Error) => setError(caught.message));
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'agents' }, '*');
  }, []);

  useEffect(() => {
    selectedIdRef.current = selectedAgentTypeId;
    if (selectedAgentTypeId) notifyActiveAgentSelection(selectedAgentTypeId);
  }, [selectedAgentTypeId]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
        dependencies?: AppDependenciesPayload;
      };
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'agents')) {
        void handleNavigationParams(payload.params || {});
      } else if (payload.type === 'maverick.app.dependencies' && payload.app_id === 'agents') {
        void refreshSkills(payload.dependencies).catch((caught: Error) => setError(caught.message));
      } else if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'agents' && payload.resource === 'configuration') {
        void refresh(selectedIdRef.current).catch((caught: Error) => setError(caught.message));
      } else if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === skillProviderAppId && payload.resource === 'skills') {
        void refreshSkills().catch((caught: Error) => setError(caught.message));
      }
    }
    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [catalog.agent_types, skillProviderAppId]);

  const selectedAgent = catalog.agent_types.find((item) => item.id === selectedAgentTypeId);

  async function saveEdits(edits: AgentEdits) {
    if (!selectedAgent) return;
    setSavingEdits(true);
    setError('');
    try {
      const selection = skillIdsForAgentSave(selectedAgent, edits.skillIds, skills);
      if (
        edits.name !== selectedAgent.name ||
        edits.description !== selectedAgent.description ||
        edits.instructions !== selectedAgent.instructions ||
        selection.changed
      ) {
        await callBackend({
          action: 'upsert_agent_definition',
          id: selectedAgent.id,
          name: edits.name,
          description: edits.description,
          instructions: edits.instructions,
          skill_ids: selection.skillIds,
          enabled: selectedAgent.enabled
        });
        await refresh(selectedAgent.id);
      }
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSavingEdits(false);
    }
  }

  async function createAgent(payload: { name: string; instructions: string; skillIds: string[] }) {
    const id = `agent-type-${slugify(payload.name)}-${Date.now().toString(36)}`;
    setCreatingAgent(true);
    setError('');
    try {
      await callBackend({
        action: 'upsert_agent_definition',
        id,
        name: payload.name,
        description: '',
        instructions: payload.instructions,
        skill_ids: payload.skillIds,
        enabled: true
      });
      setNewAgentModalOpen(false);
      await refresh(id);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setCreatingAgent(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeletingAgent(true);
    setError('');
    try {
      await callBackend({ action: 'delete_agent_definition', id: pendingDelete.id });
      setPendingDelete(null);
      await refresh();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setDeletingAgent(false);
    }
  }

  return (
    <main className="agents-shell">
      <section className="agents-detail">
        {error ? <div className="agents-error">{error}</div> : null}
        {isCatalogLoading && !catalog.agent_types.length ? <AgentsDetailSkeleton /> : (
          <AgentsDetail
            skills={skills}
            selectedAgentType={selectedAgent}
            savingEdits={savingEdits}
            onDeleteAgentType={() => selectedAgent && setPendingDelete({ id: selectedAgent.id, name: selectedAgent.name })}
            onSaveEdits={saveEdits}
          />
        )}
      </section>
      <NewAgentModal
        open={newAgentModalOpen}
        skills={skills}
        saving={creatingAgent}
        onClose={() => !creatingAgent && setNewAgentModalOpen(false)}
        onCreate={createAgent}
      />
      {pendingDelete ? (
        <DeleteAgentTypeDialog
          agentName={pendingDelete.name}
          deleting={deletingAgent}
          onCancel={() => !deletingAgent && setPendingDelete(null)}
          onConfirm={confirmDelete}
        />
      ) : null}
    </main>
  );
}

function AgentsDetailSkeleton() {
  return <div className="agents-detail-skeleton" role="status" aria-label="Loading agents" />;
}
