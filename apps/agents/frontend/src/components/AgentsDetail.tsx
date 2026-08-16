import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Bot, FileText, Gauge, Puzzle, Save, ScrollText, Trash2, UserRound } from 'lucide-react';
import { effectiveSkillIds } from '../lib/dependencies';
import type { AgentEdits, AgentType, Catalog, Role, SkillSummary } from '../types';

type AgentsDetailProps = {
  catalog: Catalog;
  skills: SkillSummary[];
  selectedAgentType?: AgentType;
  selectedRole?: Role;
  preview: string;
  previewLoading?: boolean;
  savingEdits: boolean;
  onDeleteAgentType: () => void;
  onSaveEdits: (edits: AgentEdits) => void;
};

function cardAnimation(delay = 0) {
  return {
    initial: { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.32, delay }
  };
}

function RoleFlow({ roleName }: { roleName: string }) {
  const initials = roleName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase();

  return (
    <div className="bento-visual role-flow" aria-hidden="true">
      <motion.div
        className="role-flow-node role-flow-primary"
        animate={{ scale: [1, 1.08, 1] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: [0.16, 1, 0.3, 1] }}
      >
        {initials || 'R'}
      </motion.div>
      <div className="role-flow-lines">
        {[0, 1, 2].map((item) => (
          <motion.span
            key={item}
            animate={{ opacity: [0.28, 0.9, 0.28], width: ['42%', '100%', '58%'] }}
            transition={{ duration: 1.8, repeat: Infinity, delay: item * 0.18, ease: [0.16, 1, 0.3, 1] }}
          />
        ))}
      </div>
    </div>
  );
}

function TraceMeter({ traceVerbosity }: { traceVerbosity: string }) {
  const steps = traceVerbosity === 'verbose' ? 5 : traceVerbosity === 'compact' ? 3 : 2;

  return (
    <div className="bento-visual trace-meter" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((item) => (
        <span
          key={item}
          className={item < steps ? 'is-active' : ''}
          style={{ height: item < steps ? `${26 + item * 4}px` : '18px' }}
        />
      ))}
      <div className="trace-sweep" />
    </div>
  );
}

function skillMatchesSearch(skill: SkillSummary, query: string) {
  if (!query) return true;
  const queryParts = query.split(/[^a-z0-9]+/).filter(Boolean);
  const skillParts = `${skill.name} ${skill.id} ${skill.description}`
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  return queryParts.every((queryPart) => skillParts.some((skillPart) => skillPart.startsWith(queryPart)));
}

function sameSet(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((item) => rightSet.has(item));
}

export function AgentsDetail({
  catalog,
  skills,
  selectedAgentType,
  selectedRole,
  preview,
  previewLoading = false,
  savingEdits,
  onDeleteAgentType,
  onSaveEdits
}: AgentsDetailProps) {
  const [skillSearch, setSkillSearch] = useState('');
  const [agentName, setAgentName] = useState('');
  const [agentDescription, setAgentDescription] = useState('');
  const [roleInstructions, setRoleInstructions] = useState('');
  const [commonPrompt, setCommonPrompt] = useState('');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [skillActivationMode, setSkillActivationMode] = useState<'implicit' | 'explicit'>('implicit');
  const initialSkillIds = useMemo(
    () => (selectedAgentType ? effectiveSkillIds(selectedAgentType, skills) : []),
    [selectedAgentType, skills]
  );

  useEffect(() => {
    if (!selectedAgentType || !selectedRole) {
      setAgentName('');
      setAgentDescription('');
      setRoleInstructions('');
      setCommonPrompt(catalog.common_prompt);
      setSelectedSkillIds([]);
      setSkillActivationMode('implicit');
      return;
    }
    setAgentName(selectedAgentType.name);
    setAgentDescription(selectedAgentType.description);
    setRoleInstructions(selectedRole.instructions);
    setCommonPrompt(catalog.common_prompt);
    setSelectedSkillIds(effectiveSkillIds(selectedAgentType, skills));
    setSkillActivationMode(selectedAgentType.skill_activation_mode || 'implicit');
    setSkillSearch('');
  }, [catalog.common_prompt, selectedAgentType, selectedRole, skills]);

  if (!selectedAgentType || !selectedRole) {
    return <div className="empty-state">No agent type selected.</div>;
  }

  const selectedSkillCount = selectedSkillIds.length;
  const normalizedSkillSearch = skillSearch.trim().toLowerCase();
  const visibleSkillCount = skills.filter((skill) => skillMatchesSearch(skill, normalizedSkillSearch)).length;
  const hasEdits =
    agentName !== selectedAgentType.name ||
    agentDescription !== selectedAgentType.description ||
    roleInstructions !== selectedRole.instructions ||
    commonPrompt !== catalog.common_prompt ||
    skillActivationMode !== (selectedAgentType.skill_activation_mode || 'implicit') ||
    !sameSet(selectedSkillIds, initialSkillIds);

  function toggleSkill(skillId: string, checked: boolean) {
    setSelectedSkillIds((current) => {
      if (checked) {
        return current.includes(skillId) ? current : [...current, skillId];
      }
      return current.filter((item) => item !== skillId);
    });
  }

  function saveEdits() {
    if (!hasEdits || savingEdits) return;
    onSaveEdits({
      name: agentName,
      description: agentDescription,
      instructions: roleInstructions,
      commonPrompt,
      skillIds: selectedSkillIds,
      skillActivationMode
    });
  }

  return (
    <>
      <header className="detail-header">
        <div className="detail-title-block">
          <h2>{selectedAgentType.name}</h2>
          <span className="detail-title-separator" aria-hidden="true" />
          <p>{selectedAgentType.description}</p>
        </div>
        <div className="action-group">
          <button className="danger-action" onClick={onDeleteAgentType}>
            <Trash2 size={16} aria-hidden="true" />
            Delete Agent
          </button>
          <button className="primary-action" onClick={saveEdits} disabled={!hasEdits || savingEdits}>
            <Save size={16} aria-hidden="true" />
            {savingEdits ? 'Saving Edits' : 'Save Edits'}
          </button>
        </div>
      </header>

      <div className="agent-bento-grid">
        <motion.section className="bento-card bento-card-agent" {...cardAnimation()}>
          <div className="bento-card-topline">
            <span><Bot size={15} aria-hidden="true" /> Agent Type</span>
          </div>
          <div className="bento-card-body">
            <label>
              Name
              <input value={agentName} onChange={(event) => setAgentName(event.target.value)} />
            </label>
            <label>
              Description
              <textarea value={agentDescription} onChange={(event) => setAgentDescription(event.target.value)} />
            </label>
          </div>
        </motion.section>

        <motion.section className="bento-card bento-card-role" {...cardAnimation(0.05)}>
          <div className="bento-card-topline">
            <span><UserRound size={15} aria-hidden="true" /> Role</span>
            <strong>{selectedRole.name}</strong>
          </div>
          <RoleFlow roleName={selectedRole.name} />
          <div className="bento-card-body compact">
            <div className="bento-kpi">
              <span>Instructions</span>
              <strong>{selectedRole.instructions.trim().split(/\s+/).filter(Boolean).length} words</strong>
            </div>
            <div className="bento-kpi">
              <span>Status</span>
              <strong>{selectedAgentType.enabled ? 'Enabled' : 'Disabled'}</strong>
            </div>
          </div>
        </motion.section>

        <motion.section className="bento-card bento-card-trace" {...cardAnimation(0.1)}>
          <div className="bento-card-topline">
            <span><Gauge size={15} aria-hidden="true" /> Trace</span>
            <strong>{selectedAgentType.trace_verbosity}</strong>
          </div>
          <TraceMeter traceVerbosity={selectedAgentType.trace_verbosity} />
        </motion.section>

        <motion.section className="bento-card bento-card-instructions" {...cardAnimation(0.15)}>
          <div className="bento-card-topline">
            <span><ScrollText size={15} aria-hidden="true" /> Role Instructions</span>
          </div>
          <textarea value={roleInstructions} onChange={(event) => setRoleInstructions(event.target.value)} />
        </motion.section>

        <motion.section className="bento-card bento-card-common" {...cardAnimation(0.2)}>
          <div className="bento-card-topline">
            <span><FileText size={15} aria-hidden="true" /> Common Prompt</span>
          </div>
          <textarea value={commonPrompt} onChange={(event) => setCommonPrompt(event.target.value)} />
        </motion.section>

        <motion.section className="bento-card bento-card-skills" {...cardAnimation(0.25)}>
          <div className="bento-card-topline">
            <span><Puzzle size={15} aria-hidden="true" /> Skills</span>
            <strong>{selectedSkillCount} installed</strong>
          </div>
          <div className="skill-scroll-shell">
            <label>
              Activation mode
              <select value={skillActivationMode} onChange={(event) => setSkillActivationMode(event.target.value as 'implicit' | 'explicit')}>
                <option value="implicit">Implicit — expose configured skills</option>
                <option value="explicit">Explicit — load only when invoked</option>
              </select>
            </label>
            <div className="skill-search-frame">
              <span className="material-symbols-rounded" aria-hidden="true">search</span>
              <input
                aria-label="Search skills"
                className="skill-search-input"
                id="skill-search"
                type="search"
                value={skillSearch}
                onChange={(event) => setSkillSearch(event.target.value)}
                placeholder="Search skills"
              />
            </div>
            <div className="skill-picker agent-skill-picker">
              {skills.length ? (
                skills.map((skill) => (
                  <label
                    className={`skill-choice ${skillMatchesSearch(skill, normalizedSkillSearch) ? '' : 'is-filtered-out'}`}
                    key={`${selectedAgentType.id}-${skill.id}`}
                  >
                    <input
                      type="checkbox"
                      name="agent-skill"
                      value={skill.id}
                      checked={selectedSkillIds.includes(skill.id)}
                      onChange={(event) => toggleSkill(skill.id, event.target.checked)}
                    />
                    <span>
                      <strong>{skill.name}</strong>
                      <small>{skill.description || skill.id}</small>
                    </span>
                  </label>
                ))
              ) : (
                <div className="empty-state compact">No workspace skills available.</div>
              )}
              {skills.length && !visibleSkillCount ? <div className="empty-state compact">No skills match this search.</div> : null}
            </div>
          </div>
        </motion.section>
      </div>

      <section className="editor-band prompt-review-band">
        <div className="band-heading">
          <h3>Prompt Preview</h3>
        </div>
        {previewLoading ? (
          <div className="agents-preview-skeleton" role="status" aria-label="Loading prompt preview">
            <span className="agents-preview-skeleton__line agents-preview-skeleton__line--wide" />
            <span className="agents-preview-skeleton__line agents-preview-skeleton__line--medium" />
            <span className="agents-preview-skeleton__line agents-preview-skeleton__line--short" />
            <span className="agents-preview-skeleton__line agents-preview-skeleton__line--wide" />
          </div>
        ) : (
          <pre>{preview}</pre>
        )}
      </section>
    </>
  );
}
