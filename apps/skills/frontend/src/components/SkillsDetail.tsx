import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { BookOpen, FileText, Fingerprint, Layers3, Save, ScrollText, Trash2, ToggleLeft } from 'lucide-react';
import type { Catalog, SkillDetail, SkillEdits } from '../types';

type SkillsDetailProps = {
  catalog: Catalog;
  selectedSkill: SkillDetail | null;
  savingSkill: boolean;
  onDeleteSkill: () => void;
  onDirtyChange?: (hasEdits: boolean) => void;
  onSaveSkill: (edits: SkillEdits) => void;
};

function cardAnimation(delay = 0) {
  return {
    initial: { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.32, delay }
  };
}

function OriginFlow({ origin }: { origin: string }) {
  return (
    <div className="bento-visual origin-flow" aria-hidden="true">
      <motion.div
        className="origin-flow-node"
        animate={{ scale: [1, 1.08, 1] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: [0.16, 1, 0.3, 1] }}
      >
        {origin.slice(0, 1).toUpperCase() || 'S'}
      </motion.div>
      <div className="origin-flow-lines">
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

function StatusMeter({ enabled }: { enabled: boolean }) {
  const steps = enabled ? 4 : 2;

  return (
    <div className="bento-visual status-meter" aria-hidden="true">
      {[0, 1, 2, 3].map((item) => (
        <motion.span
          key={item}
          className={item < steps ? 'is-active' : ''}
          animate={{ height: item < steps ? [22, 36, 26] : 18 }}
          transition={{ duration: 1.8, repeat: Infinity, delay: item * 0.12, ease: [0.16, 1, 0.3, 1] }}
        />
      ))}
      <motion.div
        className="status-sweep"
        animate={{ x: ['-120%', '120%'] }}
        transition={{ duration: 2.1, repeat: Infinity, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  );
}

function wordCount(value: string) {
  return value.trim().split(/\s+/).filter(Boolean).length;
}

function formatDate(value: string) {
  if (!value) return 'Unknown';
  return new Date(value).toLocaleDateString();
}

export function skillDraftFromDetail(skill: SkillDetail): SkillEdits {
  return {
    name: skill.name,
    description: skill.description,
    content: skill.content,
    enabled: skill.enabled
  };
}

export function hasUnsavedSkillEdits(draft: SkillEdits, selectedSkill: SkillDetail | null): boolean {
  if (!selectedSkill) {
    return false;
  }
  return (
    draft.name !== selectedSkill.name ||
    draft.description !== selectedSkill.description ||
    draft.content !== selectedSkill.content ||
    draft.enabled !== selectedSkill.enabled
  );
}

export function SkillsDetail({ catalog, selectedSkill, savingSkill, onDeleteSkill, onDirtyChange, onSaveSkill }: SkillsDetailProps) {
  const [skillName, setSkillName] = useState('');
  const [skillDescription, setSkillDescription] = useState('');
  const [skillContent, setSkillContent] = useState('');
  const [skillEnabled, setSkillEnabled] = useState(true);
  const selectedSkillRef = useRef<SkillDetail | null>(null);

  const draft = {
    name: skillName,
    description: skillDescription,
    content: skillContent,
    enabled: skillEnabled
  };
  const hasEdits = hasUnsavedSkillEdits(draft, selectedSkill);
  const draftRef = useRef<SkillEdits>(draft);
  draftRef.current = draft;

  useEffect(() => {
    if (!selectedSkill) {
      selectedSkillRef.current = null;
      setSkillName('');
      setSkillDescription('');
      setSkillContent('');
      setSkillEnabled(true);
      return;
    }
    const previousSkill = selectedSkillRef.current;
    const shouldReplaceDraft =
      !previousSkill || previousSkill.id !== selectedSkill.id || !hasUnsavedSkillEdits(draftRef.current, previousSkill);
    selectedSkillRef.current = selectedSkill;
    if (shouldReplaceDraft) {
      const nextDraft = skillDraftFromDetail(selectedSkill);
      setSkillName(nextDraft.name);
      setSkillDescription(nextDraft.description);
      setSkillContent(nextDraft.content);
      setSkillEnabled(nextDraft.enabled);
    }
  }, [selectedSkill]);

  useEffect(() => {
    onDirtyChange?.(hasEdits);
  }, [hasEdits, onDirtyChange]);

  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  if (!selectedSkill) {
    return <div className="empty-state">No skill selected.</div>;
  }

  const canSave = selectedSkill.editable && hasEdits && !savingSkill;

  function saveSkill() {
    if (!canSave) return;
    onSaveSkill({
      name: skillName,
      description: skillDescription,
      content: skillContent,
      enabled: skillEnabled
    });
  }

  return (
    <>
      <header className="detail-header">
        <div className="detail-title-block">
          <h2>{selectedSkill.name}</h2>
          <span className="detail-title-separator" aria-hidden="true" />
          <p>{selectedSkill.description || 'No description set.'}</p>
        </div>
        <div className="action-group">
          <button className="danger-action" onClick={onDeleteSkill} disabled={!selectedSkill.deletable}>
            <Trash2 size={16} aria-hidden="true" />
            Delete Skill
          </button>
          <button className="primary-action" onClick={saveSkill} disabled={!canSave}>
            <Save size={16} aria-hidden="true" />
            {savingSkill ? 'Saving Edits' : 'Save Edits'}
          </button>
        </div>
      </header>

      <div className="skill-bento-grid">
        <motion.section className="bento-card bento-card-skill" {...cardAnimation()}>
          <div className="bento-card-topline">
            <span><BookOpen size={15} aria-hidden="true" /> Skill</span>
          </div>
          <div className="bento-card-body">
            <label>
              Name
              <input value={skillName} onChange={(event) => setSkillName(event.target.value)} disabled={!selectedSkill.editable} />
            </label>
            <label>
              Description
              <textarea
                value={skillDescription}
                onChange={(event) => setSkillDescription(event.target.value)}
                disabled={!selectedSkill.editable}
              />
            </label>
          </div>
          <div className="skill-card-status">
            <div className="bento-card-topline">
              <span><ToggleLeft size={15} aria-hidden="true" /> Status</span>
              <strong>{skillEnabled ? 'Enabled' : 'Disabled'}</strong>
            </div>
            <StatusMeter enabled={skillEnabled} />
            <label className="skill-toggle-choice">
              <input
                type="checkbox"
                checked={skillEnabled}
                onChange={(event) => setSkillEnabled(event.target.checked)}
                disabled={!selectedSkill.editable}
              />
              Enabled for runtime sessions
            </label>
          </div>
        </motion.section>

        <motion.section className="bento-card bento-card-origin" {...cardAnimation(0.05)}>
          <div className="bento-card-topline">
            <span><Layers3 size={15} aria-hidden="true" /> Origin</span>
            <strong>{selectedSkill.origin}</strong>
          </div>
          <OriginFlow origin={selectedSkill.origin} />
          <div className="bento-card-body compact">
            <div className="bento-kpi">
              <span>Workspace Skills</span>
              <strong>{catalog.skills.length}</strong>
            </div>
            <div className="bento-kpi">
              <span>Updated</span>
              <strong>{formatDate(selectedSkill.updated_at)}</strong>
            </div>
          </div>
        </motion.section>

        <motion.section className="bento-card bento-card-instructions" {...cardAnimation(0.15)}>
          <div className="bento-card-topline">
            <span><ScrollText size={15} aria-hidden="true" /> Instructions</span>
            <strong>{wordCount(skillContent)} words</strong>
          </div>
          <textarea value={skillContent} onChange={(event) => setSkillContent(event.target.value)} disabled={!selectedSkill.editable} />
        </motion.section>

        <motion.section className="bento-card bento-card-identity" {...cardAnimation(0.1)}>
          <div className="bento-card-topline">
            <span><Fingerprint size={15} aria-hidden="true" /> Identity</span>
            <strong>{selectedSkill.local_id}</strong>
          </div>
          <div className="skill-identity-list">
            <div>
              <span>Skill ID</span>
              <strong>{selectedSkill.id}</strong>
            </div>
            <div>
              <span>Source</span>
              <strong>{selectedSkill.source_path || 'workspace skill catalog'}</strong>
            </div>
          </div>
        </motion.section>

        <motion.section className="bento-card bento-card-preview" {...cardAnimation(0.25)}>
          <div className="bento-card-topline">
            <span><FileText size={15} aria-hidden="true" /> SKILL.md Preview</span>
          </div>
          <pre>{selectedSkill.markdown}</pre>
        </motion.section>
      </div>
    </>
  );
}
