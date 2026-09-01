import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BookOpen, Search } from 'lucide-react';
import { callBackend } from '../../api';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { skillIdFromSelectionMessage, skillIdFromWidgetContext, type ActiveSkillSelectionMessage } from '../../lib/activeSkillSelection';
import type { Catalog, SkillSummary, ViewFilterPayload } from '../../types';
import '../../styles/sidebar-widget.css';

const emptyCatalog: Catalog = { skills: [] };
const MOBILE_LAYOUT_QUERY = '(max-width: 979px)';

function isMobileLayoutViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  try {
    const shellWindow = window.parent && window.parent !== window ? window.parent : window;
    return typeof shellWindow.matchMedia === 'function' && shellWindow.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  } catch {
    return typeof window.matchMedia === 'function' && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
  }
}

function useShellMobileLayout() {
  const [isShellMobileLayout, setIsShellMobileLayout] = useState(isMobileLayoutViewport);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    let mediaQuery: MediaQueryList;
    try {
      const shellWindow = window.parent && window.parent !== window ? window.parent : window;
      mediaQuery = shellWindow.matchMedia(MOBILE_LAYOUT_QUERY);
    } catch {
      mediaQuery = window.matchMedia(MOBILE_LAYOUT_QUERY);
    }
    const update = () => setIsShellMobileLayout(mediaQuery.matches);
    update();
    mediaQuery.addEventListener('change', update);
    return () => mediaQuery.removeEventListener('change', update);
  }, []);

  return isShellMobileLayout;
}

function openSkillInShell(skillId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'skills',
      params: {
        app_page: `skills/${skillId}`,
        skill_id: skillId
      }
    },
    "*"
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, "*");
  }
}

function skillMatchesSearch(skill: SkillSummary, query: string) {
  if (!query) return true;
  return `${skill.name} ${skill.description} ${skill.id} ${skill.origin}`.toLowerCase().includes(query);
}

function SkillsSidebarWidget() {
  const [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [query, setQuery] = useState('');
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return catalog.skills.filter((item) => skillMatchesSearch(item, needle));
  }, [catalog.skills, query]);

  async function refreshCatalog() {
    const next = await callBackend<Catalog>({ action: 'catalog' });
    setCatalog(next);
    setSelectedSkillId((current) => {
      if (current && next.skills.some((item) => item.id === current)) {
        return current;
      }
      return next.skills[0]?.id || '';
    });
  }

  async function refreshViewFilter() {
    const payload = await callBackend<ViewFilterPayload>({ action: 'view_filter' });
    const nextQuery = payload.state?.view_filter?.query || '';
    lastPersistedQueryRef.current = nextQuery;
    hasLoadedViewStateRef.current = true;
    setQuery(nextQuery);
  }

  async function refreshAll() {
    try {
      await Promise.all([refreshCatalog(), refreshViewFilter()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load skills.');
    } finally {
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (!hasLoadedViewStateRef.current || query === lastPersistedQueryRef.current) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = query.trim();
      callBackend<ViewFilterPayload>({ action: 'set_view_filter', query: nextQuery, entity_type: 'skill' })
        .then(() => {
          lastPersistedQueryRef.current = nextQuery;
          setError(null);
        })
        .catch((saveError: Error) => setError(saveError.message));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [query]);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
        return;
      }
      const payload = event.data as {
        context?: Record<string, unknown>;
        owner_app_id?: string;
        resource?: string;
        type?: string;
      } & ActiveSkillSelectionMessage;
      const contextSkillId = skillIdFromWidgetContext(payload);
      if (contextSkillId) {
        setSelectedSkillId(contextSkillId);
        return;
      }
      const activeSkillId = skillIdFromSelectionMessage(payload);
      if (activeSkillId) {
        setSelectedSkillId(activeSkillId);
        return;
      }
      if (payload.type !== 'maverick.widget.data-changed' || payload.owner_app_id !== 'skills') {
        return;
      }
      if (payload.resource === 'skills') {
        void refreshCatalog();
      }
      if (payload.resource === 'view-state') {
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function selectSkill(skill: SkillSummary) {
    setSelectedSkillId(skill.id);
    openSkillInShell(skill.id);
  }

  return (
    <main className={`skills-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="skills-sidebar-search-frame">
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search skills"
          className="skills-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search skills"
          value={query}
        />
      </div>

      {error ? <p className="skills-sidebar-empty">{error}</p> : null}

      <div className="skills-sidebar-list">
        {isInitialLoading ? (
          <SkillsSidebarSkeleton />
        ) : filteredSkills.length ? (
          filteredSkills.map((skill) => (
            <button
              className={`skills-sidebar-row ${skill.id === selectedSkillId ? 'is-active' : ''}`}
              key={skill.id}
              onClick={() => selectSkill(skill)}
              type="button"
            >
              <span className="skills-sidebar-row__icon" aria-hidden="true">
                <BookOpen size={17} />
              </span>
              <span className="skills-sidebar-row__copy">
                <strong>{skill.name}</strong>
                <span>{skill.origin === 'workspace' ? skill.id : `${skill.local_id} · ${skill.origin}`}</span>
              </span>
            </button>
          ))
        ) : (
          <p className="skills-sidebar-empty">No skills found.</p>
        )}
      </div>
    </main>
  );
}

function SkillsSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="skills-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="skills-sidebar-skeleton__row" key={index}>
          <span className="skills-sidebar-skeleton__icon" />
          <span className="skills-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('skills-sidebar-root') as HTMLElement).render(<SkillsSidebarWidget />);
