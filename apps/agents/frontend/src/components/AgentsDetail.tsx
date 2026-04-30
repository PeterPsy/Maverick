import type { AgentType, Catalog, Role, SkillSummary } from '../types';

type AgentsDetailProps = {
  catalog: Catalog;
  skills: SkillSummary[];
  selectedAgentType?: AgentType;
  selectedRole?: Role;
  preview: string;
  savingPrompt: boolean;
  onDeleteAgentType: () => void;
  onSaveAgentType: () => void;
  onSaveRole: () => void;
  onSaveCommonPrompt: () => void;
};

export function AgentsDetail({
  catalog,
  skills,
  selectedAgentType,
  selectedRole,
  preview,
  savingPrompt,
  onDeleteAgentType,
  onSaveAgentType,
  onSaveRole,
  onSaveCommonPrompt
}: AgentsDetailProps) {
  if (!selectedAgentType || !selectedRole) {
    return <div className="empty-state">No agent type selected.</div>;
  }

  return (
    <>
      <header className="detail-header">
        <div>
          <h2>{selectedAgentType.name}</h2>
          <p>{selectedAgentType.description}</p>
        </div>
        <div className="action-group">
          <button className="danger-action" onClick={onDeleteAgentType}>
            <span className="material-symbols-rounded" aria-hidden="true">delete</span>
            Delete Agent
          </button>
        </div>
      </header>

      <div className="meta-grid">
        <div><span>Role</span><strong>{selectedRole.name}</strong></div>
        <div><span>Trace</span><strong>{selectedAgentType.trace_verbosity}</strong></div>
      </div>

      <section className="editor-band">
        <div className="band-heading">
          <h3>Agent Type</h3>
          <button onClick={onSaveAgentType}>
            <span className="material-symbols-rounded" aria-hidden="true">save</span>
            Save
          </button>
        </div>
        <input id="agent-type-name" key={`${selectedAgentType.id}-name`} defaultValue={selectedAgentType.name} />
        <textarea id="agent-type-description" key={`${selectedAgentType.id}-description`} defaultValue={selectedAgentType.description} />
      </section>

      <section className="editor-band">
        <div className="band-heading">
          <h3>Role Instructions</h3>
          <button onClick={onSaveRole}>
            <span className="material-symbols-rounded" aria-hidden="true">save</span>
            Save
          </button>
        </div>
        <textarea id="role-instructions" key={selectedRole.id} defaultValue={selectedRole.instructions} />
      </section>

      <section className="editor-band">
        <div className="band-heading">
          <h3>Common Prompt</h3>
          <button onClick={onSaveCommonPrompt} disabled={savingPrompt}>
            <span className="material-symbols-rounded" aria-hidden="true">{savingPrompt ? 'progress_activity' : 'save'}</span>
            {savingPrompt ? 'Saving' : 'Save'}
          </button>
        </div>
        <textarea id="common-prompt" defaultValue={catalog.common_prompt} />
      </section>

      <section className="editor-band">
        <h3>Prompt Preview</h3>
        <pre>{preview}</pre>
      </section>

      <details className="editor-band skill-collapsible agent-skill-collapsible">
        <summary>
          <span>Skills</span>
          <small>{selectedAgentType.skill_ids.length || skills.length} installed</small>
        </summary>
        <div className="skill-picker agent-skill-picker">
          {skills.length ? (
            skills.map((skill) => (
              <label className="skill-choice" key={`${selectedAgentType.id}-${skill.id}`}>
                <input
                  type="checkbox"
                  name="agent-skill"
                  value={skill.id}
                  defaultChecked={selectedAgentType.skill_ids.length ? selectedAgentType.skill_ids.includes(skill.id) : true}
                />
                <span>
                  <strong>{skill.name}</strong>
                  <small>{skill.description || skill.id}</small>
                </span>
              </label>
            ))
          ) : (
            <div className="empty-state">No workspace skills available.</div>
          )}
        </div>
        <div className="skill-footer">
          <button onClick={onSaveAgentType}>
            <span className="material-symbols-rounded" aria-hidden="true">save</span>
            Save Skills
          </button>
        </div>
      </details>
    </>
  );
}
