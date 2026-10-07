import { getAppDependencies, requestJson, saveAppDependencySelection, type AppDependenciesPayload } from './adminApi';
import { connectAppEventSocket } from '@maverick/pwa-cache';
import { bindLearningTickets } from './learningTicketBindings';

export type LearningSettings = {
  enabled: boolean; paused: boolean; memory_enabled: boolean; improvements_enabled: boolean;
  memory_mode: string; idle_seconds: number; model_source: string; model_id: string; reasoning_effort: string;
  max_context_chars: number; max_output_tokens: number; timeout_seconds: number; daily_token_budget: number;
  excluded_thread_ids: string[]; excluded_project_ids: string[]; instructions: string; retention_days: number;
  improvement_concurrency?: number;
};
export type LearningJob = {
  id: string; session_id: string; status: string; attempts: number; created_at: number;
  usage: number; reserved: number; error: string; model: string; input?: unknown; output_text?: string;
};
export type LearningItem = {
  id: string; kind: string; title: string; body: string; status: string; occurrences: number;
  node_id: string; provider_id: string;
  implementation?: { status: string; session_id: string; turn_id: string; error: string; summary: string; created_at: number; updated_at: number; attempt: number };
  evidence: { session_id: string; turn_id: string; role: string; quote: string; metrics: Record<string, number> }[];
  details: { memory_matches?: { id: string; title: string }[]; memory_check_error?: string; save_error?: string;
    node_created?: boolean; category?: string; expected_impact?: string; effort?: string; verification?: string };
};
export type LearningData = {
  settings: LearningSettings; jobs: LearningJob[]; items: LearningItem[]; concurrency: number;
  daily_tokens_reserved_or_used: number;
  counts?: { pending_memory: number; pending_improvements: number; queued: number; running: number; failed: number; budget_waiting?: number; open_memory?: number; open_improvement?: number };
  conversations: { session_id: string; project_id: string; last_activity: number; label?: string }[];
  audit: { id: number; action: string; target: string; actor: string; created_at: number }[];
  projects?: { memory?: string; improvement?: string };
  runtime_ready?: boolean;
};
export type LearningView = {
  data: LearningData | null; error: string; loading: boolean; saving: boolean;
  tab: 'memory' | 'improvements' | 'analyses' | 'audit'; detail: LearningJob | null;
  dependency: AppDependenciesPayload | null; dirty: boolean;
  notice?: string; openSections?: string[]; selectedSession?: string;
  draftSettings?: Partial<LearningSettings>;
  ticketView?: 'board' | 'list'; ticketFilter?: 'open' | 'all' | 'closed'; ticketSearch?: string; ticketCategory?: string;
};

export function createLearningController(context: { render: () => void; workspaceId: () => string }) {
  let state: LearningView = { data: null, error: '', loading: false, saving: false, tab: 'memory', detail: null, dependency: null, dirty: false };
  let scope = '';
  let generation = 0;
  let loadEpoch = 0;
  let detailEpoch = 0;
  let stopSocket: (() => void) | null = null;
  let visible = false;
  let invalidated = false;
  const drafts = new Map<string, string | boolean>();
  const itemDrafts = new Map<string, string>();
  const ticketViews = new Map<string, Partial<LearningView>>();
  const call = <T>(body: object) => requestJson<T>('/api/apps/chat/backend', { method: 'POST', body: JSON.stringify(body) });

  function closeSocket() {
    stopSocket?.();
    stopSocket = null;
  }

  function render() {
    const boardScroll = document.querySelector('.learning-kanban')?.scrollLeft || 0;
    const active = document.activeElement;
    const selector = active?.id ? `#${active.id}` : active?.getAttribute('name') ? `[name="${active.getAttribute('name')}"]`
      : ['data-learning-title', 'data-learning-body', 'data-learning-target'].map((attr) => active?.hasAttribute(attr) ? `[${attr}="${active.getAttribute(attr)}"]` : '').find(Boolean);
    const selection = active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement ? [active.selectionStart, active.selectionEnd] : null;
    const sections = new Set(state.openSections);
    document.querySelectorAll<HTMLDetailsElement>('[data-learning-disclosure]').forEach((element) => {
      if (element.open) sections.add(element.dataset.learningDisclosure!); else sections.delete(element.dataset.learningDisclosure!);
    });
    state.openSections = [...sections];
    context.render();
    const board = document.querySelector('.learning-kanban');
    if (board) board.scrollLeft = boardScroll;
    const replacement = selector ? document.querySelector<HTMLElement>(selector) : null;
    replacement?.focus({ preventScroll: true });
    if (selection?.[0] != null && (replacement instanceof HTMLTextAreaElement || replacement instanceof HTMLInputElement && ['text', 'search'].includes(replacement.type))) replacement.setSelectionRange(selection[0], selection[1]);
  }

  function reset() {
    generation++;
    scope = '';
    invalidated = false;
    drafts.clear();
    itemDrafts.clear();
    ticketViews.clear();
    closeSocket();
    state = { data: null, error: '', loading: false, saving: false, tab: 'memory', detail: null, dependency: null, dirty: false };
  }

  function connect() {
    if (!visible || stopSocket) return;
    const revision = generation;
    const refresh = () => { if (revision === generation) { invalidated = true; if (!state.saving) void load(true); } };
    stopSocket = connectAppEventSocket<{ workspace_id?: string; owner_app_id?: string; resource?: string }>((change) => {
      if (change.workspace_id === scope && change.owner_app_id === 'chat' && change.resource === 'learning') refresh();
    }, refresh);
  }

  async function load(force = false) {
    const workspace = context.workspaceId();
    if (!workspace) return;
    if (scope !== workspace) { reset(); scope = workspace; }
    if (state.loading || (!force && state.data)) return;
    const revision = generation;
    const epoch = ++loadEpoch;
    invalidated = false;
    state.loading = true;
    if (!state.data) render();
    try {
      const [data, dependency] = await Promise.all([
        call<LearningData>({ action: 'learning.read' }), getAppDependencies('chat')
      ]);
      if (revision !== generation || epoch !== loadEpoch || workspace !== context.workspaceId()) return;
      state.data = data;
      state.dependency = dependency;
      state.error = '';
    } catch (error) {
      if (revision === generation && epoch === loadEpoch) state.error = message(error);
    } finally {
      if (revision === generation && epoch === loadEpoch) { state.loading = false; render(); if (invalidated && !state.saving && visible) void load(true); }
    }
  }

  async function mutate(body: object, before?: () => Promise<unknown>) {
    if (state.saving) return;
    const revision = generation;
    loadEpoch++;
    state.loading = false;
    state.saving = true;
    state.error = '';
    state.notice = '';
    render();
    try {
      if (before) await before();
      if (revision !== generation) return;
      await call(body);
      if (revision !== generation) return;
      const action = body as { action?: string; item_id?: string; command?: string; settings?: Record<string, unknown> };
      if (action.action === 'learning.configure' && action.settings && 'enabled' in action.settings) drafts.clear();
      state.notice = action.action === 'learning.configure' ? 'Settings saved' : ['accept', 'approve', 'start', 'retry'].includes(action.command || '') ? 'Ticket queued. Its work chat appears when the agent starts.' : action.command === 'implemented' ? 'Implementation confirmed.' : action.command === 'stop' ? 'Stop requested. This chat keeps its slot until the turn ends.' : 'Action completed';
      if (action.item_id) for (const key of itemDrafts.keys()) if (key.endsWith(':' + action.item_id)) itemDrafts.delete(key);
      state.dirty = drafts.size > 0 || itemDrafts.size > 0;
      await load(true);
    } catch (error) {
      if (revision === generation) state.error = message(error);
    } finally {
      if (revision === generation) { state.saving = false; render(); if (invalidated && visible) void load(true); }
    }
  }

  async function save(form: HTMLFormElement) {
    const values = new FormData(form);
    const settings: Record<string, unknown> = {};
    settings.paused = state.data!.settings.paused;
    for (const key of ['enabled', 'memory_enabled', 'improvements_enabled']) settings[key] = values.get(key) === 'on';
    for (const key of ['idle_seconds', 'max_context_chars', 'max_output_tokens', 'timeout_seconds', 'daily_token_budget', 'retention_days']) settings[key] = Number(values.get(key));
    if (values.has('improvement_concurrency')) settings.improvement_concurrency = Number(values.get('improvement_concurrency'));
    for (const key of ['memory_mode', 'model_source', 'model_id', 'reasoning_effort', 'instructions']) settings[key] = String(values.get(key) || '');
    for (const key of ['excluded_thread_ids', 'excluded_project_ids']) settings[key] = String(values.get(key) || '').split(/[\s,]+/).filter(Boolean);
    const provider = String(values.get('memory_provider') || '');
    const selected = state.dependency?.dependencies.find((item) => item.alias === 'learning-memory')?.selected_provider_app_ids[0] || '';
    await mutate({ action: 'learning.configure', settings }, provider !== selected
      ? () => saveAppDependencySelection('chat', 'learning-memory', provider ? [provider] : []) : undefined);
  }

  function bind() {
    const reviewItem = (itemId: string, command: string) => {
      const target = document.querySelector<HTMLSelectElement>(`[data-learning-target="${itemId}"]`)?.value || '';
      const title = document.querySelector<HTMLInputElement>(`[data-learning-title="${itemId}"]`)?.value;
      const body = document.querySelector<HTMLTextAreaElement>(`[data-learning-body="${itemId}"]`)?.value;
      void mutate({ action: 'learning.review', item_id: itemId, command, target_node_id: target === 'new' ? '' : target, confirm_new: target === 'new', title, body });
    };
    bindLearningTickets(state, reviewItem, (changes) => { Object.assign(state, changes); render(); });
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
        updateFormHints();
      };
      form.addEventListener('input', remember);
      form.addEventListener('change', remember);
      updateFormHints();
    }
    form?.addEventListener('submit', (event) => { event.preventDefault(); void save(form); });
    document.querySelector('#learning-refresh')?.addEventListener('click', () => { void load(true); });
    document.querySelector('#learning-discard')?.addEventListener('click', () => { state.dirty = false; drafts.clear(); itemDrafts.clear(); state.notice = ''; render(); });
    document.querySelector('#learning-pause')?.addEventListener('click', () => { void mutate({ action: 'learning.configure', settings: { paused: !state.data!.settings.paused } }); });
    document.querySelector<HTMLSelectElement>('#learning-session')?.addEventListener('change', (event) => { state.selectedSession = (event.target as HTMLSelectElement).value; render(); });
    document.querySelectorAll<HTMLDetailsElement>('[data-learning-disclosure]').forEach((element) => {
      element.open = Boolean(state.openSections?.includes(element.dataset.learningDisclosure!));
      element.addEventListener('toggle', () => {
        if (!element.isConnected) return;
        const sections = new Set(state.openSections);
        if (element.open) sections.add(element.dataset.learningDisclosure!); else sections.delete(element.dataset.learningDisclosure!);
        state.openSections = [...sections];
      });
    });
    document.querySelector('#learning-analyze')?.addEventListener('click', () => {
      const session = document.querySelector<HTMLSelectElement>('#learning-session')?.value;
      if (session) void mutate({ action: 'learning.analyze_now', session_id: session });
    });
    for (const attribute of ['data-learning-title', 'data-learning-body', 'data-learning-target']) {
      document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(`[${attribute}]`).forEach((element) => {
        const key = attribute + ':' + element.getAttribute(attribute);
        if (itemDrafts.has(key)) element.value = itemDrafts.get(key)!;
        element.addEventListener('input', () => { itemDrafts.set(key, element.value); state.dirty = true; updateFormHints(); });
      });
    }
    document.querySelectorAll<HTMLAnchorElement>('.learning-results a[href^="/app/"]').forEach((link) => link.addEventListener('click', (event) => {
      if (window.parent === window || event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      const parts = new URL(link.href).pathname.split('/').filter(Boolean);
      const origin = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__ || '*';
      window.parent.postMessage({ type: 'maverick.app.open-app', app_id: decodeURIComponent(parts[1]), params: { app_page: parts.slice(2).map(decodeURIComponent).join('/') } }, origin);
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-tab]').forEach((button) => button.addEventListener('click', () => {
      ticketViews.set(state.tab, { ticketView: state.ticketView, ticketFilter: state.ticketFilter, ticketSearch: state.ticketSearch, ticketCategory: state.ticketCategory });
      detailEpoch++; state.tab = button.dataset.learningTab as LearningView['tab']; state.detail = null;
      Object.assign(state, { ticketView: undefined, ticketFilter: undefined, ticketSearch: undefined, ticketCategory: undefined }, ticketViews.get(state.tab));
      render();
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-tab]').forEach((button, index, buttons) => button.addEventListener('keydown', (event) => {
      const next = { ArrowRight: (index + 1) % buttons.length, ArrowLeft: (index + buttons.length - 1) % buttons.length, Home: 0, End: buttons.length - 1 }[event.key];
      if (next !== undefined) { event.preventDefault(); buttons[next].click(); document.querySelector<HTMLElement>(`#${buttons[next].id}`)?.focus(); }
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-job]').forEach((button) => button.addEventListener('click', async () => {
      const jobId = button.dataset.learningJob;
      const command = button.dataset.learningCommand;
      if (command !== 'inspect') { await mutate({ action: 'learning.job', job_id: jobId, command }); return; }
      const revision = generation;
      const epoch = ++detailEpoch;
      try {
        const result = await call<{ job: LearningJob }>({ action: 'learning.job', job_id: jobId, command });
        if (revision === generation && epoch === detailEpoch) { state.detail = result.job; render(); }
      } catch (error) { if (revision === generation && epoch === detailEpoch) { state.error = message(error); render(); } }
    }));
    document.querySelectorAll<HTMLElement>('[data-learning-item]').forEach((button) => button.addEventListener('click', () => {
      const itemId = button.dataset.learningItem;
      reviewItem(itemId!, button.dataset.learningCommand!);
    }));
  }

  function setVisible(value: boolean) {
    visible = value;
    if (!value) { closeSocket(); return; }
    if (scope) connect();
    if (invalidated && !state.saving) void load(true);
  }
  function updateFormHints() {
    const status = document.querySelector('#learning-draft-status');
    if (status) status.textContent = state.dirty ? 'Unsaved changes' : state.notice || 'Settings are up to date';
    const discard = document.querySelector<HTMLButtonElement>('#learning-discard');
    if (discard) discard.disabled = !state.dirty || state.saving;
    const memory = document.querySelector<HTMLInputElement>('[name=memory_enabled]');
    const options = document.querySelector<HTMLElement>('#learning-memory-options');
    if (options && memory) options.hidden = !memory.checked;
    const source = document.querySelector<HTMLSelectElement>('[name=model_source]')?.value;
    document.querySelectorAll<HTMLElement>('[data-learning-native]').forEach((element) => { element.hidden = source !== 'workspace'; });
    const hint = document.querySelector('#learning-mode-hint');
    if (hint) hint.textContent = document.querySelector<HTMLSelectElement>('[name=memory_mode]')?.value === 'automatic' ? 'Only explicit user facts with verified quotes and no Memory matches are saved automatically.' : 'You approve each fact before it enters Memory.';
  }
  function viewState(): LearningView {
    const draftSettings: Record<string, unknown> = {};
    for (const [key, value] of drafts) {
      if (key === 'memory_provider' || !state.data) continue;
      const original = state.data.settings[key as keyof LearningSettings];
      draftSettings[key] = typeof original === 'number' ? Number(value) : Array.isArray(original) ? String(value).split(/[\s,]+/).filter(Boolean) : value;
    }
    return { ...state, draftSettings };
  }
  return { load, reset, bind, setVisible, viewState };
}

function message(error: unknown) { return error instanceof Error ? error.message : 'Learning operation failed'; }
