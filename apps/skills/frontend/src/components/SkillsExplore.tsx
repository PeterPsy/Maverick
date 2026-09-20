import { FormEvent, useEffect, useState } from 'react';
import { Download, ExternalLink, FileText, Search, ShieldAlert, X } from 'lucide-react';
import { callBackend } from '../api';
import type { RemoteSkillDetail, RemoteSkillSummary, SkillDetail } from '../types';

const SKILL_ID_PATTERN = /^[a-z][a-z0-9-]{1,62}$/;

export function isValidLocalSkillId(value: string) {
  return SKILL_ID_PATTERN.test(value);
}

export function defaultLocalSkillId(value: string) {
  let normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
    .replace(/-+$/g, '');
  if (!/^[a-z]/.test(normalized)) normalized = `skill-${normalized}`;
  if (normalized.length < 2) normalized = `skill-${normalized || 'imported'}`;
  return normalized.slice(0, 63).replace(/-+$/g, '');
}

export function SkillsExplore({ onInstalled }: { onInstalled: (skillId: string) => void | Promise<void> }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<RemoteSkillSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<RemoteSkillDetail | null>(null);
  const [selectedFile, setSelectedFile] = useState('SKILL.md');
  const [localId, setLocalId] = useState('');
  const [searching, setSearching] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    setLoadingDetail(true);
    setError('');
    callBackend<{ remote_skill: RemoteSkillDetail }>({ action: 'prompts_chat.get_skill', remote_id: selectedId })
      .then((payload) => {
        if (!active) return;
        setDetail(payload.remote_skill);
        setLocalId(defaultLocalSkillId(payload.remote_skill.slug || payload.remote_skill.title));
        setSelectedFile(payload.remote_skill.files.some((file) => file.filename === 'SKILL.md')
          ? 'SKILL.md'
          : payload.remote_skill.files[0]?.filename || '');
      })
      .catch((loadError: Error) => active && setError(loadError.message))
      .finally(() => active && setLoadingDetail(false));
    return () => {
      active = false;
    };
  }, [selectedId]);

  async function search(event: FormEvent) {
    event.preventDefault();
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return;
    setSearching(true);
    setError('');
    setDetail(null);
    setSelectedId('');
    try {
      const payload = await callBackend<{ skills: RemoteSkillSummary[] }>({
        action: 'prompts_chat.search_skills',
        query: normalizedQuery,
        limit: 5,
      });
      setResults(payload.skills || []);
    } catch (searchError) {
      setError((searchError as Error).message);
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  async function install() {
    if (!detail || !isValidLocalSkillId(localId)) return;
    setInstalling(true);
    setError('');
    try {
      const payload = await callBackend<{ skill: SkillDetail }>({
        action: 'prompts_chat.install_skill',
        remote_id: detail.id,
        local_id: localId,
        confirmed: true,
        expected_content_sha256: detail.content_sha256,
      });
      setConfirming(false);
      await onInstalled(payload.skill.id);
    } catch (installError) {
      setError((installError as Error).message);
      setConfirming(false);
    } finally {
      setInstalling(false);
    }
  }

  const activeFile = detail?.files.find((file) => file.filename === selectedFile) || null;

  return (
    <section className="skills-explore" aria-labelledby="skills-explore-title">
      <header className="skills-explore__header">
        <div>
          <h2 id="skills-explore-title">Discover Agent Skills</h2>
          <p>Search prompts.chat, review every file, then install an exact local copy.</p>
        </div>
        <span className="skills-explore__trust"><ShieldAlert size={15} /> External content is untrusted</span>
      </header>

      <form className="skills-explore__search" onSubmit={search}>
        <Search size={18} aria-hidden="true" />
        <input
          aria-label="Search prompts.chat Agent Skills"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search Agent Skills"
          value={query}
        />
        <button className="primary-action" disabled={searching || !query.trim()} type="submit">
          {searching ? 'Searching' : 'Search'}
        </button>
      </form>

      {error ? <div className="skills-error">{error}</div> : null}

      <div className="skills-explore__layout">
        <div className="skills-explore__results" aria-label="Search results">
          {!results.length ? (
            <p className="empty-state">Search the public catalog to find an Agent Skill.</p>
          ) : results.map((skill) => (
            <button
              className={`skills-explore__result ${selectedId === skill.id ? 'is-active' : ''}`}
              key={skill.id}
              onClick={() => setSelectedId(skill.id)}
              type="button"
            >
              <strong>{skill.title || skill.slug}</strong>
              <span>{skill.description || 'No description provided.'}</span>
              <small>{skill.author || 'Unknown author'} · {skill.files.length} files</small>
            </button>
          ))}
        </div>

        <div className="skills-explore__detail">
          {loadingDetail ? <p className="empty-state">Loading the complete skill…</p> : null}
          {!loadingDetail && !detail ? <p className="empty-state">Select a result to inspect all files.</p> : null}
          {detail ? (
            <>
              <header className="skills-explore__detail-header">
                <div>
                  <h3>{detail.title || detail.slug}</h3>
                  <p>{detail.description || 'No description provided.'}</p>
                </div>
                <a href={detail.link} rel="noreferrer" target="_blank">
                  prompts.chat <ExternalLink size={14} aria-hidden="true" />
                </a>
              </header>
              <div className="skills-explore__meta">
                <span>By {detail.author || 'Unknown author'}</span>
                <span>{detail.files.length} files</span>
                <span>Digest {detail.content_sha256.slice(0, 12)}…</span>
              </div>
              <div className="skills-explore__files" aria-label="Remote skill files">
                {detail.files.map((file) => (
                  <button
                    className={file.filename === selectedFile ? 'is-active' : ''}
                    key={file.filename}
                    onClick={() => setSelectedFile(file.filename)}
                    type="button"
                  >
                    <FileText size={14} aria-hidden="true" /> {file.filename}
                  </button>
                ))}
              </div>
              <pre className="skills-explore__preview">{activeFile?.content || ''}</pre>
              <div className="skills-explore__install-row">
                <label>
                  Workspace skill ID
                  <input value={localId} onChange={(event) => setLocalId(event.target.value)} />
                </label>
                <button
                  className="primary-action"
                  disabled={!isValidLocalSkillId(localId)}
                  onClick={() => setConfirming(true)}
                  type="button"
                >
                  <Download size={15} aria-hidden="true" /> Install reviewed skill
                </button>
              </div>
              {!isValidLocalSkillId(localId) ? <p className="skills-explore__validation">Use lowercase kebab-case, 2–63 characters.</p> : null}
            </>
          ) : null}
        </div>
      </div>

      {confirming && detail ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => !installing && setConfirming(false)}>
          <section className="maverick-modal install-skill-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <h2>Install Agent Skill</h2>
                <p>Save the reviewed files as <strong>{localId}</strong>.</p>
              </div>
              <button className="icon-action" disabled={installing} onClick={() => setConfirming(false)} type="button" aria-label="Close">
                <X size={16} />
              </button>
            </header>
            <div className="install-skill-summary">
              <strong>{detail.title || detail.slug}</strong>
              <span>{detail.files.map((file) => file.filename).join(', ')}</span>
              <code>{detail.content_sha256}</code>
            </div>
            <footer className="modal-actions">
              <button className="secondary-action" disabled={installing} onClick={() => setConfirming(false)} type="button">Cancel</button>
              <button className="primary-action" disabled={installing} onClick={install} type="button">
                {installing ? 'Installing' : 'Install exact copy'}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}
