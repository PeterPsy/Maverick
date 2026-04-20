import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/main.css';

type SkillSummary = {
  id: string;
  local_id: string;
  name: string;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  origin: string;
  source_path: string;
  editable: boolean;
  deletable: boolean;
};

type SkillDetail = SkillSummary & {
  content: string;
  markdown: string;
};

type Catalog = {
  skills: SkillSummary[];
};

const emptyCatalog: Catalog = { skills: [] };

function newSkillId() {
  return `skill-custom-${Date.now().toString(36)}`;
}

async function callBackend<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch('/api/apps/skills/backend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || 'Skills request failed');
  }
  return payload as T;
}

function App() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [selectedSkill, setSelectedSkill] = useState<SkillDetail | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  async function refresh(preferredSkillId?: string) {
    const next = await callBackend<Catalog>({ action: 'catalog' });
    setCatalog(next);
    setSelectedSkillId((current) => {
      if (preferredSkillId && next.skills.some((item) => item.id === preferredSkillId)) {
        return preferredSkillId;
      }
      if (current && next.skills.some((item) => item.id === current)) {
        return current;
      }
      return next.skills[0]?.id || '';
    });
  }

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!selectedSkillId) {
      setSelectedSkill(null);
      return;
    }
    callBackend<{ skill: SkillDetail }>({ action: 'get_skill', skill_id: selectedSkillId })
      .then((payload) => setSelectedSkill(payload.skill))
      .catch((err: Error) => setError(err.message));
  }, [selectedSkillId]);

  const filteredSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return catalog.skills;
    return catalog.skills.filter((item) => {
      return `${item.name} ${item.description} ${item.id}`.toLowerCase().includes(needle);
    });
  }, [catalog.skills, query]);

  async function createSkill() {
    const id = newSkillId();
    setError('');
    try {
      await callBackend({
        action: 'create_skill',
        id,
        name: 'New Skill',
        description: 'Describe when this skill should be used.',
        enabled: true
      });
      setQuery('');
      await refresh(id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function saveSkill() {
    if (!selectedSkill) return;
    if (!selectedSkill.editable) {
      setError('This skill source is not writable by the Maverick host.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const name = (document.getElementById('skill-name') as HTMLInputElement | null)?.value || selectedSkill.name;
      const description =
        (document.getElementById('skill-description') as HTMLTextAreaElement | null)?.value || selectedSkill.description;
      const content = (document.getElementById('skill-content') as HTMLTextAreaElement | null)?.value || selectedSkill.content;
      const enabled = Boolean((document.getElementById('skill-enabled') as HTMLInputElement | null)?.checked);
      const payload = await callBackend<{ skill: SkillDetail }>({
        action: 'update_skill',
        id: selectedSkill.id,
        name,
        description,
        content,
        enabled
      });
      setSelectedSkill(payload.skill);
      await refresh(selectedSkill.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function deleteSelectedSkill() {
    if (!selectedSkill) return;
    if (!selectedSkill.deletable) {
      setError('Installed agent skills cannot be deleted from this workspace.');
      return;
    }
    const confirmed = window.confirm(`Delete ${selectedSkill.name}?`);
    if (!confirmed) return;
    setError('');
    try {
      await callBackend({ action: 'delete_skill', skill_id: selectedSkill.id });
      setSelectedSkill(null);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function importInstalledSkill() {
    if (!selectedSkill) return;
    setSaving(true);
    setError('');
    try {
      const payload = await callBackend<{ skill: SkillDetail }>({
        action: 'import_installed_skill',
        skill_id: selectedSkill.id
      });
      setSelectedSkill(payload.skill);
      setQuery('');
      await refresh(payload.skill.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="skills-shell">
      <section className="skills-sidebar">
        <div className="skills-titlebar">
          <div>
            <p className="skills-eyebrow">Maverick</p>
            <h1>Skills</h1>
          </div>
          <div className="skills-titlebar-actions">
            <span>{catalog.skills.length}</span>
            <button className="skills-new-button" onClick={createSkill} type="button" aria-label="Create skill">
              <span className="material-symbols-rounded" aria-hidden="true">add</span>
            </button>
          </div>
        </div>
        <input
          className="skills-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search skills"
          aria-label="Search skills"
        />
        <div className="skills-list">
          {filteredSkills.map((skill) => (
            <button
              key={skill.id}
              className={skill.id === selectedSkillId ? 'skill-row selected' : 'skill-row'}
              onClick={() => setSelectedSkillId(skill.id)}
            >
              <span className="skill-row-icon material-symbols-rounded" aria-hidden="true">psychology</span>
              <span className="skill-row-copy">
                <strong>{skill.name}</strong>
                <span>{skill.origin === 'workspace' ? skill.id : `${skill.local_id} · ${skill.origin}`}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="skills-detail">
        {error ? <div className="skills-error">{error}</div> : null}
        {selectedSkill ? (
          <>
            <header className="detail-header">
              <div>
                <h2>{selectedSkill.name}</h2>
                <p>{selectedSkill.description || 'No description set.'}</p>
              </div>
              <div className="action-group">
                {selectedSkill.editable ? (
                  <>
                    <button className="danger-action" onClick={deleteSelectedSkill} disabled={!selectedSkill.deletable}>
                      <span className="material-symbols-rounded" aria-hidden="true">delete</span>
                      Delete Skill
                    </button>
                    <button className="primary-action" onClick={saveSkill} disabled={saving}>
                      <span className="material-symbols-rounded" aria-hidden="true">{saving ? 'progress_activity' : 'save'}</span>
                      {saving ? 'Saving' : 'Save Skill'}
                    </button>
                  </>
                ) : (
                  <button className="primary-action" onClick={importInstalledSkill} disabled={saving}>
                    <span className="material-symbols-rounded" aria-hidden="true">{saving ? 'progress_activity' : 'download'}</span>
                    {saving ? 'Importing' : 'Import Skill'}
                  </button>
                )}
              </div>
            </header>

            <div className="meta-grid">
              <div><span>Skill ID</span><strong>{selectedSkill.id}</strong></div>
              <div><span>Origin</span><strong>{selectedSkill.origin}</strong></div>
              <div><span>Status</span><strong>{selectedSkill.enabled ? 'enabled' : 'disabled'}</strong></div>
              <div><span>Updated</span><strong>{new Date(selectedSkill.updated_at).toLocaleDateString()}</strong></div>
            </div>
            {selectedSkill.source_path ? (
              <section className="source-band">
                <span>Source</span>
                <strong>{selectedSkill.source_path}</strong>
              </section>
            ) : null}

            <section className="editor-band">
              <div className="band-heading">
                <h3>Skill Metadata</h3>
                <label className="toggle-row">
                  <input
                    id="skill-enabled"
                    type="checkbox"
                    key={`${selectedSkill.id}-enabled`}
                    defaultChecked={selectedSkill.enabled}
                    disabled={!selectedSkill.editable}
                  />
                  Enabled
                </label>
              </div>
              <input id="skill-name" key={`${selectedSkill.id}-name`} defaultValue={selectedSkill.name} disabled={!selectedSkill.editable} />
              <textarea
                id="skill-description"
                key={`${selectedSkill.id}-description`}
                defaultValue={selectedSkill.description}
                placeholder="When should Codex use this skill?"
                disabled={!selectedSkill.editable}
              />
            </section>

            <section className="editor-band">
              <div className="band-heading">
                <h3>Skill Instructions</h3>
                <button onClick={saveSkill} disabled={saving || !selectedSkill.editable}>
                  <span className="material-symbols-rounded" aria-hidden="true">{saving ? 'progress_activity' : 'save'}</span>
                  {saving ? 'Saving' : 'Save'}
                </button>
              </div>
              <textarea id="skill-content" key={`${selectedSkill.id}-content`} defaultValue={selectedSkill.content} disabled={!selectedSkill.editable} />
            </section>

            <section className="editor-band">
              <h3>SKILL.md Preview</h3>
              <pre>{selectedSkill.markdown}</pre>
            </section>
          </>
        ) : (
          <div className="empty-state">No skill selected. Create one to start.</div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(<App />);
