import { useEffect, useState } from 'react';
import type { SkillSummary } from '../types';

type NewAgentModalProps = {
  open: boolean;
  skills: SkillSummary[];
  saving: boolean;
  onClose: () => void;
  onCreate: (payload: { name: string; prompt: string; skillIds: string[] }) => Promise<void>;
};

export function NewAgentModal({ open, skills, saving, onClose, onCreate }: NewAgentModalProps) {
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return;
    setName('');
    setPrompt('');
    setSelectedSkillIds(skills.map((skill) => skill.id));
  }, [skills, open]);

  if (!open) return null;

  const canSubmit = Boolean(name.trim() && prompt.trim()) && !saving;

  async function submit() {
    if (!canSubmit) return;
    await onCreate({ name: name.trim(), prompt: prompt.trim(), skillIds: selectedSkillIds });
  }

  function toggleSkill(skillId: string) {
    setSelectedSkillIds((current) =>
      current.includes(skillId) ? current.filter((item) => item !== skillId) : [...current, skillId]
    );
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="agent-modal" role="dialog" aria-modal="true" aria-labelledby="new-agent-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal-header">
          <div>
            <h2 id="new-agent-title">New Agent</h2>
            <p>Create an agent with its own role prompt and default skills.</p>
          </div>
          <button className="icon-action" type="button" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded" aria-hidden="true">close</span>
          </button>
        </header>

        <div className="modal-body">
          <label>Name
            <input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
          </label>
          <label>Prompt
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={10} />
          </label>

          <details className="skill-collapsible" open>
            <summary>
              <span>Skills</span>
              <small>{selectedSkillIds.length}/{skills.length} selected</small>
            </summary>
            <div className="skill-picker modal-skill-picker">
              {skills.length ? (
                skills.map((skill) => (
                  <label className="skill-choice" key={skill.id}>
                    <input
                      type="checkbox"
                      checked={selectedSkillIds.includes(skill.id)}
                      onChange={() => toggleSkill(skill.id)}
                    />
                    <span>
                      <strong>{skill.name}</strong>
                      <small>{skill.description || skill.id}</small>
                    </span>
                  </label>
                ))
              ) : (
                <div className="empty-state compact">No linked workspace skills available.</div>
              )}
            </div>
          </details>
        </div>

        <footer className="modal-actions">
          <button className="secondary-action" type="button" onClick={onClose}>Cancel</button>
          <button className="primary-action" type="button" onClick={submit} disabled={!canSubmit}>
            <span className="material-symbols-rounded" aria-hidden="true">{saving ? 'progress_activity' : 'add'}</span>
            {saving ? 'Creating' : 'Create Agent'}
          </button>
        </footer>
      </section>
    </div>
  );
}
