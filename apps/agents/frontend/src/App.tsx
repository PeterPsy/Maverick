import { useEffect, useRef, useState } from 'react';
import { callBackend, callSkillsBackend } from './api';
import { AgentsDetail } from './components/AgentsDetail';
import { DeleteAgentTypeDialog } from './components/DeleteAgentTypeDialog';
import { NewAgentModal } from './components/NewAgentModal';
import { agentTypeIdFromParams, scalarString, shouldOpenNewAgent } from './lib/agentNavigationParams';
import { notifyActiveAgentSelection } from './lib/activeAgentSelection';
import type { AgentEdits, Catalog, Preview, SkillSummary } from './types';

const emptyCatalog: Catalog = { common_prompt: '', roles: [], agent_types: [] };

function slugify(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'custom-agent';
}

function initialAgentTypeId() {
  const query = new URLSearchParams(window.location.search);
  return query.get('agent_type_id') || '';
}

function sameSet(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((item) => rightSet.has(item));
}

function selectedAgentTypeIdFromCatalog(catalog: Catalog, currentAgentTypeId: string, preferredAgentTypeId?: string) {
  if (preferredAgentTypeId && catalog.agent_types.some((item) => item.id === preferredAgentTypeId)) {
    return preferredAgentTypeId;
  }
  if (currentAgentTypeId && catalog.agent_types.some((item) => item.id === currentAgentTypeId)) {
    return currentAgentTypeId;
  }
  return catalog.agent_types[0]?.id || '';
}

export function App() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState('');
  const [preview, setPreview] = useState('');
  const [previewLoadingAgentTypeId, setPreviewLoadingAgentTypeId] = useState('');
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [error, setError] = useState('');
  const [isCatalogLoading, setIsCatalogLoading] = useState(true);
  const [hasLoadedCatalog, setHasLoadedCatalog] = useState(false);
  const [savingEdits, setSavingEdits] = useState(false);
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [newAgentModalOpen, setNewAgentModalOpen] = useState(false);
  const [agentTypePendingDelete, setAgentTypePendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [deletingAgentType, setDeletingAgentType] = useState(false);
  const consumedNewAgentRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewAgentRequest = useRef(false);
  const previewCacheRef = useRef<Map<string, string>>(new Map());
  const selectedAgentTypeIdRef = useRef('');

  async function refresh(preferredAgentTypeId?: string) {
    setIsCatalogLoading(true);
    try {
      const [next, skillCatalog] = await Promise.all([
        callBackend<Catalog>({ action: 'catalog' }),
        callSkillsBackend<{ skills: SkillSummary[] }>({ action: 'catalog' })
      ]);
      const nextSelectedAgentTypeId = selectedAgentTypeIdFromCatalog(next, selectedAgentTypeIdRef.current, preferredAgentTypeId);
      selectedAgentTypeIdRef.current = nextSelectedAgentTypeId;
      setCatalog(next);
      setSkills(skillCatalog.skills.filter((skill) => skill.enabled));
      setSelectedAgentTypeId(nextSelectedAgentTypeId);
      setHasLoadedCatalog(true);
      return nextSelectedAgentTypeId;
    } finally {
      setIsCatalogLoading(false);
    }
  }

  async function refreshPreview(agentTypeId: string, options: { showCached?: boolean } = {}) {
    const cachedPreview = previewCacheRef.current.get(agentTypeId);
    if (options.showCached !== false && cachedPreview !== undefined) {
      setPreview(cachedPreview);
      setPreviewLoadingAgentTypeId('');
    } else {
      setPreview('');
      setPreviewLoadingAgentTypeId(agentTypeId);
    }
    const payload = await callBackend<Preview>({ action: 'preview_prompt', agent_type_id: agentTypeId });
    previewCacheRef.current.set(agentTypeId, payload.rendered);
    if (selectedAgentTypeIdRef.current === agentTypeId) {
      setPreview(payload.rendered);
      setPreviewLoadingAgentTypeId('');
    }
  }

  useEffect(() => {
    refresh(initialAgentTypeId()).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    selectedAgentTypeIdRef.current = selectedAgentTypeId;
  }, [selectedAgentTypeId]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'agents' }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        app_id?: string;
        owner_app_id?: string;
        params?: Record<string, string | boolean | null>;
        resource?: string;
        type?: string;
      };
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'agents')) {
        void handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'agents' && payload.resource === 'configuration') {
        previewCacheRef.current.clear();
        void refresh(selectedAgentTypeIdRef.current)
          .then((nextSelectedAgentTypeId) => {
            if (nextSelectedAgentTypeId) {
              return refreshPreview(nextSelectedAgentTypeId, { showCached: false });
            }
            return undefined;
          })
          .catch((err: Error) => setError(err.message));
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [catalog.agent_types, selectedAgentTypeId]);

  useEffect(() => {
    if (!selectedAgentTypeId) {
      setPreview('');
      setPreviewLoadingAgentTypeId('');
      return;
    }
    notifyActiveAgentSelection(selectedAgentTypeId);
    refreshPreview(selectedAgentTypeId)
      .catch((err: Error) => {
        if (selectedAgentTypeIdRef.current === selectedAgentTypeId) {
          setPreviewLoadingAgentTypeId('');
          setError(err.message);
        }
      });
  }, [selectedAgentTypeId]);

  const selectedAgentType = catalog.agent_types.find((item) => item.id === selectedAgentTypeId);
  const selectedRole = catalog.roles.find((role) => role.id === selectedAgentType?.role_id);
  const shouldShowDetailSkeleton = isCatalogLoading && !hasLoadedCatalog && !catalog.agent_types.length && !catalog.roles.length && !skills.length && !error;
  const isPreviewLoading = Boolean(selectedAgentTypeId && previewLoadingAgentTypeId === selectedAgentTypeId && !preview);

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedAgentTypeId = agentTypeIdFromParams(params);
    if (requestedAgentTypeId) {
      if (catalog.agent_types.some((item) => item.id === requestedAgentTypeId)) {
        setSelectedAgentTypeId(requestedAgentTypeId);
      } else {
        await refresh(requestedAgentTypeId);
      }
    }
    if (!shouldOpenNewAgent(params)) {
      return;
    }
    const requestId = scalarString(params.new_agent_request_id);
    if (requestId) {
      if (consumedNewAgentRequests.current.has(requestId)) {
        return;
      }
      consumedNewAgentRequests.current.add(requestId);
    } else if (consumedLegacyNewAgentRequest.current) {
      return;
    } else {
      consumedLegacyNewAgentRequest.current = true;
    }
    setNewAgentModalOpen(true);
  }

  async function saveEdits(edits: AgentEdits) {
    if (!selectedAgentType || !selectedRole) return;
    setSavingEdits(true);
    setError('');
    try {
      const implicitSkillIds = selectedAgentType.skill_ids.length ? selectedAgentType.skill_ids : skills.map((skill) => skill.id);
      const skillIdsChanged = !sameSet(edits.skillIds, implicitSkillIds);
      const operations: Promise<unknown>[] = [];

      if (
        edits.name !== selectedAgentType.name ||
        edits.description !== selectedAgentType.description ||
        skillIdsChanged
      ) {
        operations.push(
          callBackend({
            action: 'update_agent_type',
            id: selectedAgentType.id,
            role_id: selectedAgentType.role_id,
            name: edits.name,
            description: edits.description,
            skill_ids: skillIdsChanged ? edits.skillIds : selectedAgentType.skill_ids,
            trace_verbosity: selectedAgentType.trace_verbosity,
            enabled: selectedAgentType.enabled
          })
        );
      }
      if (edits.instructions !== selectedRole.instructions) {
        operations.push(
          callBackend({
            action: 'update_role',
            id: selectedRole.id,
            name: selectedRole.name,
            description: selectedRole.description,
            instructions: edits.instructions
          })
        );
      }
      if (edits.commonPrompt !== catalog.common_prompt) {
        operations.push(callBackend({ action: 'set_common_prompt', prompt: edits.commonPrompt }));
      }
      if (operations.length) {
        await Promise.all(operations);
        previewCacheRef.current.clear();
        await refresh(selectedAgentType.id);
        await refreshPreview(selectedAgentType.id, { showCached: false });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingEdits(false);
    }
  }

  async function createAgentFromModal(payload: { name: string; prompt: string; skillIds: string[] }) {
    const suffix = Date.now().toString(36);
    const slug = slugify(payload.name);
    const roleId = `${slug}-${suffix}`;
    const agentTypeId = `agent-type-${slug}-${suffix}`;
    setCreatingAgent(true);
    setError('');
    try {
      await callBackend({
        action: 'create_role',
        id: roleId,
        name: payload.name,
        description: `Role prompt for ${payload.name}.`,
        instructions: payload.prompt
      });
      await callBackend({
        action: 'create_agent_type',
        id: agentTypeId,
        name: payload.name,
        description: payload.prompt.slice(0, 180),
        role_id: roleId,
        skill_ids: payload.skillIds,
        trace_verbosity: 'compact',
        enabled: true
      });
      setNewAgentModalOpen(false);
      await refresh(agentTypeId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreatingAgent(false);
    }
  }

  async function deleteAgentType() {
    if (!selectedAgentType) return;
    setAgentTypePendingDelete({ id: selectedAgentType.id, name: selectedAgentType.name });
  }

  async function confirmDeleteAgentType() {
    if (!agentTypePendingDelete) return;
    setDeletingAgentType(true);
    setError('');
    try {
      await callBackend({ action: 'delete_agent_type', agent_type_id: agentTypePendingDelete.id });
      setAgentTypePendingDelete(null);
      await refresh();
    } catch (err) {
      setAgentTypePendingDelete(null);
      setError((err as Error).message);
    } finally {
      setDeletingAgentType(false);
    }
  }

  return (
    <main className="agents-shell">
      <section className="agents-detail">
        {error ? <div className="agents-error">{error}</div> : null}
        {shouldShowDetailSkeleton ? (
          <AgentsDetailSkeleton />
        ) : (
          <AgentsDetail
            catalog={catalog}
            skills={skills}
            selectedAgentType={selectedAgentType}
            selectedRole={selectedRole}
            preview={preview}
            previewLoading={isPreviewLoading}
            savingEdits={savingEdits}
            onDeleteAgentType={deleteAgentType}
            onSaveEdits={saveEdits}
          />
        )}
      </section>
      <NewAgentModal
        open={newAgentModalOpen}
        skills={skills}
        saving={creatingAgent}
        onClose={() => {
          if (!creatingAgent) setNewAgentModalOpen(false);
        }}
        onCreate={createAgentFromModal}
      />
      {agentTypePendingDelete ? (
        <DeleteAgentTypeDialog
          agentName={agentTypePendingDelete.name}
          deleting={deletingAgentType}
          onCancel={() => {
            if (!deletingAgentType) setAgentTypePendingDelete(null);
          }}
          onConfirm={confirmDeleteAgentType}
        />
      ) : null}
    </main>
  );
}

function AgentsDetailSkeleton() {
  return (
    <div className="agents-detail-skeleton" role="status" aria-label="Loading agents">
      <header className="detail-header agents-detail-skeleton__header" aria-hidden="true">
        <span className="agents-detail-skeleton__line agents-detail-skeleton__line--title" />
        <span className="agents-detail-skeleton__line agents-detail-skeleton__line--subtitle" />
        <span className="agents-detail-skeleton__actions">
          <span />
          <span />
        </span>
      </header>
      <div className="agent-bento-grid agents-detail-skeleton__grid" aria-hidden="true">
        <section className="bento-card bento-card-agent agents-detail-skeleton__card">
          <span className="agents-detail-skeleton__line agents-detail-skeleton__line--small" />
          <span className="agents-detail-skeleton__visual" />
          <span className="agents-detail-skeleton__field" />
          <span className="agents-detail-skeleton__field agents-detail-skeleton__field--tall" />
        </section>
        <section className="bento-card bento-card-role agents-detail-skeleton__card">
          <span className="agents-detail-skeleton__line agents-detail-skeleton__line--medium" />
          <span className="agents-detail-skeleton__rows" />
        </section>
        <section className="bento-card bento-card-trace agents-detail-skeleton__card">
          <span className="agents-detail-skeleton__line agents-detail-skeleton__line--short" />
          <span className="agents-detail-skeleton__bars" />
        </section>
        <section className="bento-card bento-card-instructions agents-detail-skeleton__card">
          <span className="agents-detail-skeleton__line agents-detail-skeleton__line--medium" />
          <span className="agents-detail-skeleton__field agents-detail-skeleton__field--fill" />
        </section>
        <section className="bento-card bento-card-common agents-detail-skeleton__card">
          <span className="agents-detail-skeleton__line agents-detail-skeleton__line--medium" />
          <span className="agents-detail-skeleton__field agents-detail-skeleton__field--fill" />
        </section>
        <section className="bento-card bento-card-skills agents-detail-skeleton__card">
          <span className="agents-detail-skeleton__line agents-detail-skeleton__line--medium" />
          <span className="agents-detail-skeleton__skill" />
          <span className="agents-detail-skeleton__skill" />
          <span className="agents-detail-skeleton__skill agents-detail-skeleton__skill--short" />
        </section>
      </div>
      <section className="editor-band prompt-review-band agents-detail-skeleton__preview" aria-hidden="true">
        <span className="agents-detail-skeleton__line agents-detail-skeleton__line--medium" />
        <span className="agents-detail-skeleton__field agents-detail-skeleton__field--preview" />
      </section>
    </div>
  );
}
