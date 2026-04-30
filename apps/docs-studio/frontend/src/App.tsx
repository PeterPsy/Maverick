import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { loadDocsState } from './api';
import { Markdown } from './Markdown';
import type { DocsPage, DocsSection, DocsState } from './types';

const iconMap: Record<string, string> = {
  spark: '*',
  bolt: 'Z',
  bulb: '!',
  shield: 'S',
  check: 'V',
  palette: 'P',
  core: '+',
  workspace: 'W',
  contract: 'C',
  agreement: 'A',
  app: '@',
  doc: 'D'
};

interface ActivePage {
  section: DocsSection;
  page: DocsPage;
}

function findFirstPage(state: DocsState | null): ActivePage | null {
  for (const section of state?.sections || []) {
    const page = section.pages[0];
    if (page) {
      return { section, page };
    }
  }
  return null;
}

function findPage(state: DocsState | null, pageId: string): ActivePage | null {
  for (const section of state?.sections || []) {
    for (const page of section.pages || []) {
      if (page.id === pageId) {
        return { section, page };
      }
    }
  }
  return null;
}

export function App() {
  const [state, setState] = useState<DocsState | null>(null);
  const [activePageId, setActivePageId] = useState('');
  const [search, setSearch] = useState('');
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState('');

  useEffect(() => {
    loadDocsState()
      .then((loaded) => {
        setState(loaded);
        setActivePageId(findFirstPage(loaded)?.page.id || '');
        setCollapsedSections(new Set(loaded.sections.slice(1).map((section) => section.id)));
      })
      .catch((error: Error) => setNotice(error.message));
  }, []);

  const active = useMemo(() => findPage(state, activePageId) || findFirstPage(state), [state, activePageId]);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timer = window.setTimeout(() => setNotice(''), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        document.getElementById('docs-search')?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const filteredSections = useMemo(() => {
    if (!state) {
      return [];
    }
    const query = search.trim().toLowerCase();
    if (!query) {
      return state.sections;
    }
    return state.sections
      .map((section) => ({
        ...section,
        pages: section.pages.filter((page) => `${page.title} ${page.summary} ${page.body}`.toLowerCase().includes(query))
      }))
      .filter((section) => section.pages.length > 0);
  }, [state, search]);

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

  if (!state || !active) {
    return <div className="loading">Loading Docs Studio...</div>;
  }

  return (
    <div className="app-shell" style={{ '--accent': state.site.accent || '#ff4f2e' } as CSSProperties}>
      <header className="topbar">
        <div className="brand-row">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">{state.site.name}</span>
        </div>
        <div>
          <div className="top-actions">
            <label className="search" aria-label="Search documentation">
              <span className="small-icon" aria-hidden="true">/</span>
              <input id="docs-search" type="search" placeholder="Search..." value={search} onChange={(event) => setSearch(event.target.value)} />
              <span className="kbd">Ctrl</span>
              <span className="kbd">K</span>
            </label>
            <button className="ask-link" type="button" onClick={() => document.getElementById('assistant-input')?.focus()}>
              <span className="small-icon" aria-hidden="true">AI</span> Ask
            </button>
            <button className="signin" type="button">Publish</button>
          </div>
          <nav className="product-tabs" aria-label="Documentation areas">
            <button className="tab active" type="button"><span aria-hidden="true">[]</span> Core Docs</button>
            <button className="tab" type="button"><span aria-hidden="true">&lt;/&gt;</span> API</button>
            <button className="tab" type="button"><span aria-hidden="true">?</span> Help center</button>
            <button className="tab" type="button"><span aria-hidden="true">#</span> Changelog</button>
          </nav>
        </div>
      </header>

      <aside className="sidebar" aria-label="Documentation navigation">
        {filteredSections.map((section) => {
          const sectionOpen = search.trim() ? true : !collapsedSections.has(section.id);
          return (
            <div className="nav-group" key={section.id}>
              <button
                className="section-toggle"
                type="button"
                aria-expanded={sectionOpen}
                onClick={() => toggleSection(section.id)}
              >
                <span>{section.title}</span>
                <span className="section-toggle-mark" aria-hidden="true">{sectionOpen ? '-' : '+'}</span>
              </button>
              <div className={`section-pages ${sectionOpen ? 'open' : ''}`} aria-hidden={!sectionOpen}>
                {section.pages.map((page) => (
                  <button
                    className={`page-link ${page.id === active.page.id ? 'active' : ''}`}
                    type="button"
                    key={page.id}
                    onClick={() => setActivePageId(page.id)}
                  >
                    <span className="page-icon" aria-hidden="true">{iconMap[page.icon] || 'D'}</span>
                    <span>{page.title}</span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </aside>

      <main className="main">
        <div className="doc-toolbar">
          <p className="eyebrow">{active.section.title}</p>
          <div className="toolbar-actions">
            <button className="chip-button" type="button" onClick={() => document.getElementById('assistant-input')?.focus()}>Ask</button>
          </div>
        </div>

        <article className="doc-page">
          <h1>{active.page.title}</h1>
          <p className="lead">{active.page.summary || state.site.tagline}</p>

          <section className="markdown-preview" aria-label="Documentation body">
            <Markdown markdown={active.page.body} />
          </section>
        </article>
      </main>

      <aside className="assistant" aria-label="Docs assistant">
        <div className="assistant-header">
          <div className="assistant-title">
            <span className="small-icon" aria-hidden="true">AI</span>
            <span>Docs Assistant</span>
          </div>
          <div className="assistant-actions">
            <button className="icon-button" type="button" title="Clear">x</button>
            <button className="icon-button" type="button" title="Close">X</button>
          </div>
        </div>
        <div className="assistant-body">
          <div className="assistant-empty">
            <div className="assistant-orb" aria-hidden="true">DS</div>
            <h2>Good morning</h2>
            <p>I'm here to help you with the core docs.</p>
          </div>
          <div className="suggestions">
            <button className="suggestion" type="button">Summarize this architecture page.</button>
            <button className="suggestion" type="button">Find missing implementation checks.</button>
            <button className="suggestion" type="button">Turn this section into onboarding docs.</button>
          </div>
          <div className="composer">
            <input id="assistant-input" type="text" placeholder="How should we improve this page?" />
            <div className="composer-footer">
              <span><strong>AI</strong> Based on your docs context</span>
              <button className="send-button" type="button" onClick={() => setNotice('Assistant prompt captured for this page.')}>Send</button>
            </div>
          </div>
        </div>
      </aside>

      <div className={`notice ${notice ? 'visible' : ''}`} role="status">{notice}</div>
    </div>
  );
}
