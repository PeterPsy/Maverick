import { useEffect, useMemo, useState } from 'react';
import { callBackend, callStorageProvider, type Page, type Site, type StorageFile } from './api';

type Notice = { tone: 'ok' | 'warn' | 'error'; text: string } | null;

export function App() {
  const [sites, setSites] = useState<Site[]>([]);
  const [activeSiteId, setActiveSiteId] = useState('');
  const [pages, setPages] = useState<Page[]>([]);
  const [activePageId, setActivePageId] = useState('');
  const [previewHtml, setPreviewHtml] = useState('');
  const [showNewWebsite, setShowNewWebsite] = useState(false);
  const [gitDialogOpen, setGitDialogOpen] = useState(false);
  const [gitUrl, setGitUrl] = useState('');
  const [gitBranch, setGitBranch] = useState('');
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);

  const activeSite = useMemo(() => sites.find((site) => site.id === activeSiteId), [sites, activeSiteId]);
  const activePage = useMemo(() => pages.find((page) => page.id === activePageId), [pages, activePageId]);
  const importOnly = showNewWebsite || !activeSite;

  async function refresh(nextSiteId = activeSiteId, nextPageId = activePageId) {
    const sitePayload = await callBackend<{ items: Site[] }>({ action: 'sites_list' });
    setSites(sitePayload.items);
    const selectedSite = nextSiteId || sitePayload.items[0]?.id || '';
    setActiveSiteId(selectedSite);
    if (!selectedSite) {
      setPages([]);
      setActivePageId('');
      setPreviewHtml('');
      setShowNewWebsite(true);
      return;
    }

    const map = await callBackend<{ items: Page[] }>({ action: 'sitemap', site_id: selectedSite });
    setPages(map.items);
    const selectedPage = map.items.find((page) => page.id === nextPageId) || map.items[0];
    setActivePageId(selectedPage?.id || '');
    if (selectedPage) {
      await renderSite(selectedSite, selectedPage.route);
    } else {
      setPreviewHtml('');
    }
  }

  async function renderSite(siteId: string, route = '/') {
    const payload = await callBackend<{ html: string }>({ action: 'build_preview', site_id: siteId, route });
    setPreviewHtml(payload.html || '');
  }

  useEffect(() => {
    refresh().catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { type?: string; params?: Record<string, string> };
      if (payload.type !== 'maverick.app.navigate') return;
      if (payload.params?.new_website_request_id) {
        setShowNewWebsite(true);
        setNotice(null);
        return;
      }
      if (payload.params?.site_id) {
        setShowNewWebsite(false);
        refresh(payload.params.site_id, payload.params.page_id || '').catch((error: Error) => setNotice({ tone: 'error', text: error.message }));
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  async function run<T>(fn: () => Promise<T>, message?: string) {
    setBusy(true);
    setNotice(null);
    try {
      const result = await fn();
      if (message) setNotice({ tone: 'ok', text: message });
      return result;
    } catch (error) {
      setNotice({ tone: 'error', text: error instanceof Error ? error.message : String(error) });
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function importZip(fileInput: File | null) {
    if (!fileInput) return;
    const encoded = await toBase64(fileInput);
    const displayName = fileInput.name.replace(/\.zip$/i, '').replace(/[-_]+/g, ' ').trim() || 'Imported Website';
    const payload = await run(
      async () => {
        const stored = await writeZipToStorage(fileInput, encoded);
        return callBackend<{ site: Site }>({
          action: 'import_zip',
          display_name: displayName,
          archive_base64: encoded,
          source_artifact_ref: storageArtifactRef(stored.file, fileInput)
        });
      },
      'ZIP imported'
    );
    if (payload?.site) {
      setShowNewWebsite(false);
      await refresh(payload.site.id);
    }
  }

  async function importGit() {
    const repositoryUrl = gitUrl.trim();
    if (!repositoryUrl) {
      setNotice({ tone: 'warn', text: 'Repository URL is required.' });
      return;
    }
    const payload = await run(
      () =>
        callBackend<{ site: Site }>({
          action: 'import_git',
          repository_url: repositoryUrl,
          branch: gitBranch.trim() || undefined
        }),
      'Git repository imported'
    );
    if (payload?.site) {
      setGitDialogOpen(false);
      setShowNewWebsite(false);
      setGitUrl('');
      setGitBranch('');
      await refresh(payload.site.id);
    }
  }

  return (
    <main className={importOnly ? 'website-studio-shell import-mode' : 'website-studio-shell site-mode'}>
      {notice ? <div className={`notice ${notice.tone}`}>{notice.text}</div> : null}

      {importOnly ? (
        <section className="import-screen" aria-label="New website">
          <div className="import-actions">
            <label className="import-button">
              Drop ZIP
              <input type="file" accept=".zip,application/zip" onChange={(event) => importZip(event.target.files?.[0] || null)} disabled={busy} />
            </label>
            <button className="import-button" onClick={() => setGitDialogOpen(true)} disabled={busy}>Connect Git</button>
          </div>
          {gitDialogOpen ? (
            <form
              className="git-import"
              onSubmit={(event) => {
                event.preventDefault();
                void importGit();
              }}
            >
              <input
                value={gitUrl}
                onChange={(event) => setGitUrl(event.target.value)}
                placeholder="https://github.com/company/site.git"
                autoComplete="off"
                disabled={busy}
              />
              <input
                value={gitBranch}
                onChange={(event) => setGitBranch(event.target.value)}
                placeholder="branch"
                autoComplete="off"
                disabled={busy}
              />
              <div className="git-import-actions">
                <button type="button" onClick={() => setGitDialogOpen(false)} disabled={busy}>Cancel</button>
                <button type="submit" disabled={busy}>Import</button>
              </div>
            </form>
          ) : null}
        </section>
      ) : (
        <section className="site-canvas" aria-label={activeSite?.display_name || 'Website'}>
          {previewHtml ? (
            <iframe title={activePage?.title || activeSite?.display_name || 'Website preview'} sandbox="" srcDoc={previewHtml} />
          ) : (
            <div className="site-empty">No renderable page in this site.</div>
          )}
        </section>
      )}
    </main>
  );
}

async function writeZipToStorage(file: File, contentBase64: string): Promise<{ file?: StorageFile }> {
  const safeName = file.name.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '') || 'website.zip';
  return callStorageProvider<{ file?: StorageFile }>('storage-writer', {
    action: 'file.content.write',
    workspace_relative_path: `storage/uploaded/website-studio/${Date.now()}-${safeName}`,
    mode: 'create',
    content_base64: contentBase64,
    content_type: file.type || 'application/zip'
  });
}

function storageArtifactRef(file: StorageFile | undefined, fallback: File): Record<string, string> {
  return {
    app_id: 'storage',
    file_id: file?.file_id || file?.id || '',
    workspace_relative_path: file?.workspace_relative_path || '',
    role: file?.role || 'uploaded',
    relative_path: file?.relative_path || '',
    name: file?.name || fallback.name,
    content_type: file?.content_type || fallback.type || 'application/zip',
    sha256: file?.sha256 || ''
  };
}

async function toBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  let binary = '';
  for (const byte of new Uint8Array(buffer)) binary += String.fromCharCode(byte);
  return btoa(binary);
}
