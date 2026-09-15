import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Bot, Puzzle, Save, ScrollText, Trash2 } from 'lucide-react';
import { effectiveSkillIds } from '../lib/dependencies';
import type { AgentEdits, AgentType, SkillSummary } from '../types';

type AgentsDetailProps = {
  skills: SkillSummary[];
  selectedAgentType?: AgentType;
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

function skillMatchesSearch(skill: SkillSummary, query: string) {
  if (!query) return true;
  return `${skill.name} ${skill.id} ${skill.description}`.toLowerCase().includes(query);
}

function sameSet(left: string[], right: string[]) {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((item) => rightSet.has(item));
}

export function AgentsDetail({
  skills,
  selectedAgentType,
  savingEdits,
  onDeleteAgentType,
  onSaveEdits
}: AgentsDetailProps) {
  const [skillSearch, setSkillSearch] = useState('');
  const [agentName, setAgentName] = useState('');
  const [agentDescription, setAgentDescription] = useState('');
  const [instructions, setInstructions] = useState('');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const initialSkillIds = useMemo(
    () => (selectedAgentType ? effectiveSkillIds(selectedAgentType, skills) : []),
    [selectedAgentType, skills]
  );

  useEffect(() => {
    setAgentName(selectedAgentType?.name || '');
    setAgentDescription(selectedAgentType?.description || '');
    setInstructions(selectedAgentType?.instructions || '');
    setSelectedSkillIds(selectedAgentType ? effectiveSkillIds(selectedAgentType, skills) : []);
    setSkillSearch('');
  }, [selectedAgentType, skills]);

  if (!selectedAgentType) {
    return <div className="empty-state">Create an agent to get started.</div>;
  }

  const query = skillSearch.trim().toLowerCase();
  const visibleSkills = skills.filter((skill) => skillMatchesSearch(skill, query));
  const hasEdits =
    agentName !== selectedAgentType.name ||
    agentDescription !== selectedAgentType.description ||
    instructions !== selectedAgentType.instructions ||
    !sameSet(selectedSkillIds, initialSkillIds);

  function toggleSkill(skillId: string, checked: boolean) {
    setSelectedSkillIds((current) => checked
      ? Array.from(new Set([...current, skillId]))
      : current.filter((item) => item !== skillId));
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
            <Trash2 size={16} aria-hidden="true" /> Delete Agent
          </button>
          <button
            className="primary-action"
            disabled={!hasEdits || savingEdits}
            onClick={() => onSaveEdits({
              name: agentName,
              description: agentDescription,
              instructions,
              skillIds: selectedSkillIds
            })}
          >
            <Save size={16} aria-hidden="true" />
            {savingEdits ? 'Saving Edits' : 'Save Edits'}
          </button>
        </div>
      </header>

      <div className="agent-bento-grid">
        <motion.section className="bento-card bento-card-agent" {...cardAnimation()}>
          <div className="bento-card-topline">
            <span><Bot size={15} aria-hidden="true" /> Agent</span>
          </div>
          <div className="bento-card-body">
            <label>Name<input value={agentName} onChange={(event) => setAgentName(event.target.value)} /></label>
            <label>Description<textarea value={agentDescription} onChange={(event) => setAgentDescription(event.target.value)} /></label>
          </div>
        </motion.section>

        <motion.section className="bento-card bento-card-instructions" {...cardAnimation(0.05)}>
          <div className="bento-card-topline">
            <span><ScrollText size={15} aria-hidden="true" /> Instructions</span>
          </div>
          <textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} />
        </motion.section>

        <motion.section className="bento-card bento-card-skills" {...cardAnimation(0.1)}>
          <div className="bento-card-topline">
            <span><Puzzle size={15} aria-hidden="true" /> Explicit Skills</span>
            <strong>{selectedSkillIds.length} selected</strong>
          </div>
          <div className="skill-scroll-shell">
            <div className="skill-search-frame">
              <span className="material-symbols-rounded" aria-hidden="true">search</span>
              <input
                aria-label="Search skills"
                className="skill-search-input"
                type="search"
                value={skillSearch}
                onChange={(event) => setSkillSearch(event.target.value)}
                placeholder="Search skills"
              />
            </div>
            <div className="skill-picker agent-skill-picker">
              {visibleSkills.map((skill) => (
                <label className="skill-choice" key={`${selectedAgentType.id}-${skill.id}`}>
                  <input
                    type="checkbox"
                    checked={selectedSkillIds.includes(skill.id)}
                    onChange={(event) => toggleSkill(skill.id, event.target.checked)}
                  />
                  <span><strong>{skill.name}</strong><small>{skill.description || skill.id}</small></span>
                </label>
              ))}
              {!visibleSkills.length ? <div className="empty-state compact">No skills found.</div> : null}
            </div>
          </div>
        </motion.section>
      </div>
    </>
  );
}
