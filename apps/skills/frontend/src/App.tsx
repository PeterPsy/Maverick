import { useCallback, useEffect, useRef, useState } from 'react';
import { callBackend } from './api';
import { DeleteSkillDialog } from './components/DeleteSkillDialog';
import { SkillsDetail } from './components/SkillsDetail';
import { SkillsDetailSkeleton } from './components/SkillsDetailSkeleton';
import { notifyActiveSkillSelection } from './lib/activeSkillSelection';
import { scalarString, shouldCreateNewSkill, skillIdFromParams } from './lib/skillNavigationParams';
import type { Catalog, SkillDetail, SkillEdits } from './types';

const emptyCatalog: Catalog = { skills: [] };

function newSkillId() {
  return `skill-custom-${Date.now().toString(36)}`;
}

function selectedSkillIdFromCatalog(catalog: Catalog, currentSkillId: string, preferredSkillId?: string) {
  if (preferredSkillId && catalog.skills.some((item) => item.id === preferredSkillId)) {
    return preferredSkillId;
  }
  if (currentSkillId && catalog.skills.some((item) => item.id === currentSkillId)) {
    return currentSkillId;
  }
  return catalog.skills[0]?.id || '';
}

function initialSkillId() {
  const query = new URLSearchParams(window.location.search);
  return query.get('skill_id') || '';
}

export function App() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [selectedSkill, setSelectedSkill] = useState<SkillDetail | null>(null);
  const [error, setError] = useState('');
  const [isCatalogLoading, setIsCatalogLoading] = useState(true);
  const [hasLoadedCatalog, setHasLoadedCatalog] = useState(false);
  const [detailLoadingSkillId, setDetailLoadingSkillId] = useState('');
  const [savingSkill, setSavingSkill] = useState(false);
  const [creatingSkill, setCreatingSkill] = useState(false);
  const [skillPendingDelete, setSkillPendingDelete] = useState<{ id: string; name: string } | null>(null);
  const [deletingSkill, setDeletingSkill] = useState(false);
  const consumedNewSkillRequests = useRef<Set<string>>(new Set());
  const consumedLegacyNewSkillRequest = useRef(false);
  const selectedSkillIdRef = useRef('');
  const hasUnsavedSkillEditsRef = useRef(false);

  const handleDirtyChange = useCallback((hasEdits: boolean) => {
    hasUnsavedSkillEditsRef.current = hasEdits;
  }, []);

  async function refresh(preferredSkillId?: string) {
    setIsCatalogLoading(true);
    try {
      const next = await callBackend<Catalog>({ action: 'catalog' });
      const nextSelectedSkillId = selectedSkillIdFromCatalog(next, selectedSkillIdRef.current, preferredSkillId);
      selectedSkillIdRef.current = nextSelectedSkillId;
      setCatalog(next);
      setSelectedSkillId(nextSelectedSkillId);
      setHasLoadedCatalog(true);
      return nextSelectedSkillId;
    } finally {
      setIsCatalogLoading(false);
    }
  }

  async function refreshDetail(skillId: string) {
    setDetailLoadingSkillId(skillId);
    const payload = await callBackend<{ skill: SkillDetail }>({ action: 'get_skill', skill_id: skillId });
    if (selectedSkillIdRef.current === skillId) {
      setSelectedSkill(payload.skill);
      setDetailLoadingSkillId('');
    }
  }

  async function createSkillFromRequest() {
    const id = newSkillId();
    setCreatingSkill(true);
    setError('');
    try {
      await callBackend({
        action: 'create_skill',
        id,
        name: 'New Skill',
        description: 'Describe when this skill should be used.',
        enabled: true
      });
      await refresh(id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreatingSkill(false);
    }
  }

  async function handleNavigationParams(params: Record<string, string | boolean | null>) {
    const requestedSkillId = skillIdFromParams(params);
    if (requestedSkillId) {
      if (catalog.skills.some((item) => item.id === requestedSkillId)) {
        setSelectedSkillId(requestedSkillId);
      } else {
        await refresh(requestedSkillId);
      }
    }
    if (!shouldCreateNewSkill(params)) {
      return;
    }
    const requestId = scalarString(params.new_skill_request_id);
    if (requestId) {
      if (consumedNewSkillRequests.current.has(requestId)) {
        return;
      }
      consumedNewSkillRequests.current.add(requestId);
    } else if (consumedLegacyNewSkillRequest.current) {
      return;
    } else {
      consumedLegacyNewSkillRequest.current = true;
    }
    await createSkillFromRequest();
  }

  useEffect(() => {
    refresh(initialSkillId()).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    selectedSkillIdRef.current = selectedSkillId;
  }, [selectedSkillId]);

  useEffect(() => {
    window.parent?.postMessage({ type: 'maverick.app.ready', app_id: 'skills' }, window.location.origin);
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
      if (payload.type === 'maverick.app.navigate' && (!payload.app_id || payload.app_id === 'skills')) {
        void handleNavigationParams(payload.params || {});
        return;
      }
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'skills' && payload.resource === 'skills') {
        void refresh(selectedSkillIdRef.current)
          .then((nextSelectedSkillId) => {
            if (nextSelectedSkillId && !hasUnsavedSkillEditsRef.current) {
              return refreshDetail(nextSelectedSkillId);
            }
            return undefined;
          })
          .catch((err: Error) => setError(err.message));
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, [catalog.skills]);

  useEffect(() => {
    if (!selectedSkillId) {
      setSelectedSkill(null);
      setDetailLoadingSkillId('');
      return;
    }
    notifyActiveSkillSelection(selectedSkillId);
    refreshDetail(selectedSkillId).catch((err: Error) => {
      if (selectedSkillIdRef.current === selectedSkillId) {
        setDetailLoadingSkillId('');
        setError(err.message);
      }
    });
  }, [selectedSkillId]);

  async function saveSkill(edits: SkillEdits) {
    if (!selectedSkill) return;
    if (!selectedSkill.editable) {
      setError('This skill source is not writable by the Maverick host.');
      return;
    }
    setSavingSkill(true);
    setError('');
    try {
      const payload = await callBackend<{ skill: SkillDetail }>({
        action: 'update_skill',
        id: selectedSkill.id,
        name: edits.name,
        description: edits.description,
        content: edits.content,
        enabled: edits.enabled
      });
      setSelectedSkill(payload.skill);
      await refresh(selectedSkill.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingSkill(false);
    }
  }

  function deleteSkill() {
    if (!selectedSkill) return;
    setSkillPendingDelete({ id: selectedSkill.id, name: selectedSkill.name });
  }

  async function confirmDeleteSkill() {
    if (!skillPendingDelete) return;
    setDeletingSkill(true);
    setError('');
    try {
      await callBackend({ action: 'delete_skill', skill_id: skillPendingDelete.id });
      setSkillPendingDelete(null);
      setSelectedSkill(null);
      await refresh();
    } catch (err) {
      setSkillPendingDelete(null);
      setError((err as Error).message);
    } finally {
      setDeletingSkill(false);
    }
  }

  const shouldShowDetailSkeleton =
    (isCatalogLoading && !hasLoadedCatalog && !catalog.skills.length && !error) ||
    Boolean(selectedSkillId && detailLoadingSkillId === selectedSkillId && !selectedSkill);

  return (
    <main className="skills-shell">
      <section className="skills-detail">
        {error ? <div className="skills-error">{error}</div> : null}
        {shouldShowDetailSkeleton || creatingSkill ? (
          <SkillsDetailSkeleton />
        ) : (
          <SkillsDetail
            catalog={catalog}
            selectedSkill={selectedSkill}
            savingSkill={savingSkill}
            onDeleteSkill={deleteSkill}
            onDirtyChange={handleDirtyChange}
            onSaveSkill={saveSkill}
          />
        )}
      </section>
      {skillPendingDelete ? (
        <DeleteSkillDialog
          deleting={deletingSkill}
          skillName={skillPendingDelete.name}
          onCancel={() => {
            if (!deletingSkill) setSkillPendingDelete(null);
          }}
          onConfirm={confirmDeleteSkill}
        />
      ) : null}
    </main>
  );
}
