import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ChevronDown, FileText, Search } from 'lucide-react';
import { loadDocsNavigationState, readDocsViewFilter, setDocsViewFilter } from '../../api';
import { useShellSidebarCloseSwipe } from '../../hooks/useShellSidebarCloseSwipe';
import { docPageIdFromSelectionMessage, type ActiveDocSelectionMessage } from '../../lib/activeDocSelection';
import { docPageIdFromWidgetContext } from '../../lib/docNavigationParams';
import { collapsedSectionsWithPageVisible } from '../../lib/sidebarSelection';
import type { DocsNavigationPage, DocsNavigationSection, DocsNavigationState } from '../../types';
import '../../styles/sidebar-widget.css';

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
      return undefined;
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

function findFirstPage(state: DocsNavigationState | null): DocsNavigationPage | null {
  for (const section of state?.sections || []) {
    const page = section.pages[0];
    if (page) {
      return page;
    }
  }
  return null;
}

function hasPage(state: DocsNavigationState | null, pageId: string) {
  return Boolean(state?.sections.some((section) => section.pages.some((page) => page.id === pageId)));
}

function sectionContainsPage(section: DocsNavigationSection, pageId: string) {
  return section.pages.some((page) => page.id === pageId);
}

function selectedPageIdFromState(state: DocsNavigationState, currentPageId: string, preferredPageId?: string) {
  if (preferredPageId && hasPage(state, preferredPageId)) {
    return preferredPageId;
  }
  if (currentPageId && hasPage(state, currentPageId)) {
    return currentPageId;
  }
  return findFirstPage(state)?.id || '';
}

function pageMatchesSearch(page: DocsNavigationPage, query: string) {
  if (!query) {
    return true;
  }
  return `${page.title} ${page.summary} ${page.source_app_id || ''}`.toLowerCase().includes(query);
}

function openPageInShell(pageId: string) {
  window.parent?.postMessage(
    {
      type: 'maverick.widget.open-app',
      app_id: 'docs-studio',
      params: {
        app_page: `pages/${pageId}`,
        page_id: pageId
      }
    },
    window.location.origin
  );
  if (isMobileLayoutViewport()) {
    window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
  }
}

function DocsStudioSidebarWidget() {
  const [state, setState] = useState<DocsNavigationState | null>(null);
  const [query, setQuery] = useState('');
  const [selectedPageId, setSelectedPageId] = useState('');
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isShellMobileLayout = useShellMobileLayout();
  const selectedPageIdRef = useRef('');
  const stateRef = useRef<DocsNavigationState | null>(null);
  const lastPersistedQueryRef = useRef('');
  const hasLoadedViewStateRef = useRef(false);

  useShellSidebarCloseSwipe(isShellMobileLayout);

  const filteredSections = useMemo(() => {
    if (!state) {
      return [];
    }
    const needle = query.trim().toLowerCase();
    if (!needle) {
      return state.sections;
    }
    return state.sections
      .map((section) => ({
        ...section,
        pages: section.pages.filter((page) => pageMatchesSearch(page, needle))
      }))
      .filter((section) => section.pages.length > 0);
  }, [state, query]);

  async function refreshState(preferredPageId?: string) {
    const next = await loadDocsNavigationState();
    const nextSelectedPageId = selectedPageIdFromState(next, selectedPageIdRef.current, preferredPageId);
    selectedPageIdRef.current = nextSelectedPageId;
    stateRef.current = next;
    setState(next);
    setSelectedPageId(nextSelectedPageId);
    setCollapsedSections((current) => {
      const collapsed = current.size ? new Set(current) : new Set(next.sections.slice(1).map((section) => section.id));
      for (const section of next.sections) {
        if (sectionContainsPage(section, nextSelectedPageId)) {
          collapsed.delete(section.id);
        }
      }
      return collapsed;
    });
  }

  function applySelectedPageId(pageId: string) {
    if (!pageId) {
      return;
    }
    selectedPageIdRef.current = pageId;
    setSelectedPageId(pageId);
    setCollapsedSections((current) => collapsedSectionsWithPageVisible(current, stateRef.current?.sections || [], pageId));
  }

  async function refreshViewFilter() {
    const viewState = await readDocsViewFilter();
    const nextQuery = viewState.query || '';
    lastPersistedQueryRef.current = nextQuery;
    hasLoadedViewStateRef.current = true;
    setQuery(nextQuery);
  }

  async function refreshAll(preferredPageId?: string) {
    try {
      await Promise.all([refreshState(preferredPageId), refreshViewFilter()]);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load docs.');
    } finally {
      setIsInitialLoading(false);
    }
  }

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    selectedPageIdRef.current = selectedPageId;
  }, [selectedPageId]);

  useEffect(() => {
    if (!hasLoadedViewStateRef.current || query === lastPersistedQueryRef.current) {
      return undefined;
    }
    const timeout = window.setTimeout(() => {
      const nextQuery = query.trim();
      setDocsViewFilter(nextQuery)
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
      } & ActiveDocSelectionMessage;
      const contextPageId = docPageIdFromWidgetContext(payload);
      if (contextPageId) {
        applySelectedPageId(contextPageId);
        return;
      }
      const activePageId = docPageIdFromSelectionMessage(payload);
      if (activePageId) {
        applySelectedPageId(activePageId);
        return;
      }
      if (
        (payload.type !== 'maverick.widget.data-changed' && payload.type !== 'maverick.app.data-changed') ||
        payload.owner_app_id !== 'docs-studio'
      ) {
        return;
      }
      if (!payload.resource || payload.resource === 'state') {
        void refreshState(selectedPageIdRef.current || undefined);
      }
      if (payload.resource === 'view-state') {
        void refreshViewFilter();
      }
    }

    window.addEventListener('message', handleShellMessage);
    return () => window.removeEventListener('message', handleShellMessage);
  }, []);

  function toggleSection(sectionId: string) {
    setCollapsedSections((current) => {
      const next = new Set(current);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }

  function selectPage(page: DocsNavigationPage) {
    applySelectedPageId(page.id);
    openPageInShell(page.id);
  }

  return (
    <main className={`docs-studio-sidebar-widget ${isShellMobileLayout ? 'is-shell-mobile' : ''}`}>
      <div className="docs-studio-sidebar-search-frame">
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search docs"
          className="docs-studio-sidebar-search"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search docs"
          value={query}
        />
      </div>

      {error ? <p className="docs-studio-sidebar-empty">{error}</p> : null}

      <div className="docs-studio-sidebar-list">
        {isInitialLoading ? (
          <DocsStudioSidebarSkeleton />
        ) : filteredSections.length ? (
          filteredSections.map((section) => {
            const sectionOpen = query.trim() ? true : !collapsedSections.has(section.id);
            return (
              <section className="docs-studio-sidebar-section" key={section.id}>
                <button
                  aria-expanded={sectionOpen}
                  className="docs-studio-sidebar-section__toggle"
                  onClick={() => toggleSection(section.id)}
                  type="button"
                >
                  <strong>{section.title}</strong>
                  <ChevronDown size={15} aria-hidden="true" />
                </button>
                <div className={`docs-studio-sidebar-pages ${sectionOpen ? 'is-open' : ''}`} aria-hidden={!sectionOpen}>
                  {section.pages.map((page) => (
                    <button
                      className={`docs-studio-sidebar-row ${page.id === selectedPageId ? 'is-active' : ''}`}
                      key={page.id}
                      onClick={() => selectPage(page)}
                      type="button"
                    >
                      <span className="docs-studio-sidebar-row__icon" aria-hidden="true">
                        <FileText size={17} />
                      </span>
                      <span className="docs-studio-sidebar-row__copy">
                        <strong>{page.title}</strong>
                        <span>{page.summary || section.title}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            );
          })
        ) : (
          <p className="docs-studio-sidebar-empty">No docs found.</p>
        )}
      </div>
    </main>
  );
}

function DocsStudioSidebarSkeleton() {
  return (
    <div aria-hidden="true" className="docs-studio-sidebar-skeleton">
      {Array.from({ length: 6 }).map((_, index) => (
        <div className="docs-studio-sidebar-skeleton__row" key={index}>
          <span className="docs-studio-sidebar-skeleton__icon" />
          <span className="docs-studio-sidebar-skeleton__copy">
            <span />
            <span />
          </span>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById('docs-studio-sidebar-root') as HTMLElement).render(<DocsStudioSidebarWidget />);
