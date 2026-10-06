import { getAppDependencies, requestJson, saveAppDependencySelection, type AppDependenciesPayload } from './adminApi';

export type LearningSettings = {
  enabled: boolean; paused: boolean; memory_enabled: boolean; improvements_enabled: boolean;
  memory_mode: string; idle_seconds: number; model_source: string; model_id: string; reasoning_effort: string;
  max_context_chars: number; max_output_tokens: number; timeout_seconds: number; daily_token_budget: number;
  excluded_thread_ids: string[]; excluded_project_ids: string[]; instructions: string; retention_days: number;
};
export type LearningJob = {
  id: string; session_id: string; status: string; attempts: number; created_at: number;
  usage: number; reserved: number; error: string; model: string; input?: unknown; output_text?: string;
};
export type LearningItem = {
  id: string; kind: string; title: string; body: string; status: string; occurrences: number;
  node_id: string; provider_id: string;
  evidence: { session_id: string; turn_id: string; role: string; quote: string; metrics: Record<string, number> }[];
  details: { memory_matches?: { id: string; title: string }[]; memory_check_error?: string; save_error?: string;
    node_created?: boolean; category?: string; expected_impact?: string; effort?: string; verification?: string };
};
export type LearningData = {
  settings: LearningSettings; jobs: LearningJob[]; items: LearningItem[]; concurrency: number;
  daily_tokens_reserved_or_used: number;
  conversations: { session_id: string; project_id: string; last_activity: number }[];
  audit: { id: number; action: string; target: string; actor: string; created_at: number }[];
};
export type LearningView = {
  data: LearningData | null; error: string; loading: boolean; saving: boolean;
  tab: 'memory' | 'improvements' | 'analyses' | 'audit'; detail: LearningJob | null;
  dependency: AppDependenciesPayload | null; dirty: boolean;
};

export function createLearningController(context: { render: () => void; workspaceId: () => string }) {
  let state: LearningView = { data: null, error: '', loading: false, saving: false, tab: 'memory', detail: null, dependency: null, dirty: false };
  let scope = '';
  let generation = 0;
  let socket: WebSocket | null = null;
  let reconnect: ReturnType<typeof setTimeout> | null = null;
  let visible = false;
  let invalidated = false;
  const drafts = new Map<string, string | boolean>();
  const itemDrafts = new Map<string, string>();
  const call = <T>(body: object) => requestJson<T>('/api/apps/chat/backend', { method: 'POST', body: JSON.stringify(body) });

  function closeSocket() {
    const previous = socket;
    socket = null;
    if (previous) { previous.onclose = null; previous.close(); }
    if (reconnect) clearTimeout(reconnect);
    reconnect = null;
  }

  function reset() {
    generation++;
    scope = '';
    invalidated = false;
    drafts.clear();
    itemDrafts.clear();
    closeSocket();
    state = { data: null, error: '', loading: false, saving: false, tab: 'memory', detail: null, dependency: null, dirty: false };
  }

  function connect() {
    if (!visible || socket || typeof WebSocket === 'undefined') return;
    const url = new URL('/api/apps/events/ws', window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const current = new WebSocket(url);
    socket = current;
    const revision = generation;
    current.onmessage = (event) => {
      if (revision !== generation || current !== socket) return;
      try {
        const change = JSON.parse(String(event.data));
        if (change.workspace_id === scope && change.owner_app_id === 'chat' && change.resource === 'learning') {
          invalidated = true;
          if (!state.dirty && !state.saving) void load(true);
        }
      } catch { /* Ignore unrelated protocol frames. */ }
    };
    current.onclose = () => {
      if (current !== socket) return;
      socket = null;
      if (visible) reconnect = setTimeout(() => { connect(); if (!state.dirty) void load(true); }, 3000);
    };
  }

  async function load(force = false) {
    const workspace = context.workspaceId();
    if (!workspace) return;
    if (scope !== workspace) { reset(); scope = workspace; }
    if (state.loading || (!force && state.data)) return;
    const revision = generation;
    state.loading = true;
    if (!state.data) context.render();
    try {
      const [data, dependency] = await Promise.all([
        call<LearningData>({ action: 'learning.read' }), getAppDependencies('chat')
      ]);
      if (revision !== generation || workspace !== context.workspaceId()) return;
      state.data = data;
      state.dependency = dependency;
      state.error = '';
      invalidated = false;
    } catch (error) {
      if (revision === generation) state.error = message(error);
    } finally {
      if (revision === generation) { state.loading = false; context.render(); }
    }
  }

  async function mutate(body: object, before?: () => Promise<unknown>) {
    if (state.saving) return;
    const revision = generation;
    state.saving = true;
    state.error = '';
    context.render();
    try {
      if (before) await before();
      if (revision !== generation) return;
      await call(body);
      if (revision !== generation) return;
      const action = body as { action?: string; item_id?: string };
      if (action.action === 'learning.configure') drafts.clear();
      if (action.item_id) for (const key of itemDrafts.keys()) if (key.endsWith(':' + action.item_id)) itemDrafts.delete(key);
      state.dirty = drafts.size > 0 || itemDrafts.size > 0;
      await load(true);
    } catch (error) {
      if (revision === generation) state.error = message(error);
    } finally {
      if (revision === generation) { state.saving = false; context.render(); }
    }
  }

  async function save(form: HTMLFormElement) {
    const values = new FormData(form);
    const settings: Record<string, unknown> = {};
    for (const key of ['enabled', 'paused', 'memory_enabled', 'improvements_enabled']) settings[key] = values.get(key) === 'on';
    for (const key of ['idle_seconds', 'max_context_chars', 'max_output_tokens', 'timeout_seconds', 'daily_token_budget', 'retention_days']) settings[key] = Number(values.get(key));
    for (const key of ['memory_mode', 'model_source', 'model_id', 'reasoning_effort', 'instructions']) settings[key] = String(values.get(key) || '');
    for (const key of ['excluded_thread_ids', 'excluded_project_ids']) settings[key] = String(values.get(key) || '').split(/[\s,]+/).filter(Boolean);
    const provider = String(values.get('memory_provider') || '');
    const selected = state.dependency?.dependencies.find((item) => item.alias === 'learning-memory')?.selected_provider_app_ids[0] || '';
    await mutate({ action: 'learning.configure', settings }, provider !== selected
      ? () => saveAppDependencySelection('chat', 'learning-memory', provider ? [provider] : []) : undefined);
  }

  function bind() {
    const form = document.querySelector<HTMLFormElement>('#learning-settings');
    if (form) {
      for (const element of form.elements) {
        if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) || !element.name || !drafts.has(element.name)) continue;
        const value = drafts.get(element.name)!;
        if (element instanceof HTMLInputElement && element.type === 'checkbox') element.checked = value === true;
        else element.value = String(value);
      }
      const remember = () => {
        state.dirty = true;
        for (const element of form.elements) {
          if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) {
            if (element.name) drafts.set(element.name, element instanceof HTMLInputElement && element.type === 'checkbox' ? element.checked : element.value);
          }
        }
      };
      form.addEventListener('input', remember);
      form.addEventListener('change', remember);
    }
    form?.addEventListener('submit', (event) => { event.preventDefault(); void save(form); });
    document.querySelector('#learning-refresh')?.addEventListener('click', () => { state.dirty = false; drafts.clear(); itemDrafts.clear(); void load(true); });
    document.querySelector('#learning-analyze')?.addEventListener('click', () => {
      const session = document.querySelector<HTMLSelectElement>('#learning-session')?.value;
      if (session) void mutate({ action: 'learning.analyze_now', session_id: session });
    });
    for (const attribute of ['data-learning-title', 'data-learning-body', 'data-learning-target']) {
      document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`[${attribute}]`).forEach((element) => {
        const key = attribute + ':' + element.getAttribute(attribute);
        if (itemDrafts.has(key)) element.value = itemDrafts.get(key)!;
        element.addEventListener('input', () => { itemDrafts.set(key, element.value); state.dirty = true; });
      });
    }
    document.querySelectorAll<HTMLAnchorElement>('.learning-results a[href^="/app/"]').forEach((link) => link.addEventListener('click', (event) => {
      if (window.parent === window || event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      const parts = new URL(link.href).pathname.split('/').filter(Boolean);
      window.parent.postMessage({ type: 'maverick.app.open-app', app_id: decodeURIComponent(parts[1]), params: { app_page: parts.slice(2).map(decodeURIComponent).join('/') } }, window.location.origin);
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-tab]').forEach((button) => button.addEventListener('click', () => {
      state.tab = button.dataset.learningTab as LearningView['tab']; state.detail = null; context.render();
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-job]').forEach((button) => button.addEventListener('click', async () => {
      const jobId = button.dataset.learningJob;
      const command = button.dataset.learningCommand;
      if (command !== 'inspect') { await mutate({ action: 'learning.job', job_id: jobId, command }); return; }
      const revision = generation;
      try {
        const result = await call<{ job: LearningJob }>({ action: 'learning.job', job_id: jobId, command });
        if (revision === generation) { state.detail = result.job; context.render(); }
      } catch (error) { if (revision === generation) { state.error = message(error); context.render(); } }
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-item]').forEach((button) => button.addEventListener('click', () => {
      const itemId = button.dataset.learningItem;
      const target = document.querySelector<HTMLSelectElement>(`[data-learning-target="${itemId}"]`)?.value || '';
      const title = document.querySelector<HTMLInputElement>(`[data-learning-title="${itemId}"]`)?.value;
      const body = document.querySelector<HTMLTextAreaElement>(`[data-learning-body="${itemId}"]`)?.value;
      void mutate({ action: 'learning.review', item_id: itemId, command: button.dataset.learningCommand,
        target_node_id: target === 'new' ? '' : target, confirm_new: target === 'new', title, body });
    }));
  }

  function setVisible(value: boolean) {
    visible = value;
    if (!value) { closeSocket(); return; }
    if (scope) connect();
    if (invalidated && !state.dirty) void load(true);
  }
  return { load, reset, bind, setVisible, viewState: () => state };
}

function message(error: unknown) { return error instanceof Error ? error.message : 'Learning operation failed'; }
