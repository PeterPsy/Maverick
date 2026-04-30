import { useEffect, useMemo, useState } from 'react';
import { callBackend, callSkillsBackend } from './api';
import { AgentsDetail } from './components/AgentsDetail';
import { AgentsSidebar } from './components/AgentsSidebar';
import { NewAgentModal } from './components/NewAgentModal';
import type { AgentType, Catalog, Preview, SkillSummary } from './types';

const emptyCatalog: Catalog = { common_prompt: '', roles: [], agent_types: [] };

function slugify(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'custom-agent';
}

export function App() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState('');
  const [query, setQuery] = useState('');
  const [preview, setPreview] = useState('');
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [error, setError] = useState('');
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [newAgentModalOpen, setNewAgentModalOpen] = useState(false);

  async function refresh(preferredAgentTypeId?: string) {
    const [next, skillCatalog] = await Promise.all([
      callBackend<Catalog>({ action: 'catalog' }),
      callSkillsBackend<{ skills: SkillSummary[] }>({ action: 'catalog' })
    ]);
    setCatalog(next);
    setSkills(skillCatalog.skills.filter((skill) => skill.enabled));
    setSelectedAgentTypeId((current) => {
      if (preferredAgentTypeId && next.agent_types.some((item) => item.id === preferredAgentTypeId)) {
        return preferredAgentTypeId;
      }
      if (current && next.agent_types.some((item) => item.id === current)) {
        return current;
      }
      return next.agent_types[0]?.id || '';
    });
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
    return catalog.agent_types.filter((item) => `${item.name} ${item.description} ${item.role_id}`.toLowerCase().includes(needle));
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
      const selectedSkillIds = Array.from(document.querySelectorAll<HTMLInputElement>('input[name="agent-skill"]:checked')).map(
        (input) => input.value
      );
      await callBackend({
        action: 'update_agent_type',
        id: selectedAgentType.id,
        role_id: selectedAgentType.role_id,
        name,
        description,
        skill_ids: selectedSkillIds,
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
      setQuery('');
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
    const confirmed = window.confirm(`Delete ${selectedAgentType.name}?`);
    if (!confirmed) return;
    setError('');
    try {
      await callBackend({ action: 'delete_agent_type', agent_type_id: selectedAgentType.id });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <main className="agents-shell">
      <AgentsSidebar
        catalog={catalog}
        query={query}
        selectedAgentTypeId={selectedAgentTypeId}
        filteredAgentTypes={filteredAgentTypes}
        onCreate={() => setNewAgentModalOpen(true)}
        onSetQuery={setQuery}
        onSelectAgentType={setSelectedAgentTypeId}
      />

      <section className="agents-detail">
        {error ? <div className="agents-error">{error}</div> : null}
        <AgentsDetail
          catalog={catalog}
          skills={skills}
          selectedAgentType={selectedAgentType}
          selectedRole={selectedRole}
          preview={preview}
          savingPrompt={savingPrompt}
          onDeleteAgentType={deleteAgentType}
          onSaveAgentType={saveAgentType}
          onSaveRole={saveRole}
          onSaveCommonPrompt={saveCommonPrompt}
        />
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
    </main>
  );
}
