// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createLearningController, type LearningData } from './learningController';
import { learningPageHtml } from './learningPage';
import { settingsPageIdFromParams } from './pages';
import { ticketCommandForMove } from './learningTickets';

const api = vi.hoisted(() => ({ request: vi.fn(), dependencies: vi.fn(), select: vi.fn() }));
const events = vi.hoisted(() => ({ subscribe: vi.fn(), stop: vi.fn() }));
vi.mock('./adminApi', () => ({ requestJson: api.request, getAppDependencies: api.dependencies, saveAppDependencySelection: api.select }));
vi.mock('@maverick/pwa-cache', () => ({ connectAppEventSocket: events.subscribe }));
const fixture = (): LearningData => ({
  settings: { enabled: true, paused: false, memory_enabled: true, improvements_enabled: true, memory_mode: 'review', idle_seconds: 120,
    model_source: 'workspace', model_id: '', reasoning_effort: 'low', max_context_chars: 30000, max_output_tokens: 2048, timeout_seconds: 120,
    daily_token_budget: 100000, excluded_thread_ids: [], excluded_project_ids: [], instructions: '', retention_days: 30 },
  jobs: [], items: [], audit: [], conversations: [], concurrency: 1, daily_tokens_reserved_or_used: 0
});

describe('Conversation learning Settings', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.dependencies.mockResolvedValue({ workspace_id: 'default', consumer_app_id: 'chat', dependencies: [] });
    api.request.mockResolvedValue(fixture());
    events.subscribe.mockReturnValue(events.stop);
    document.body.innerHTML = '';
  });
  afterEach(() => vi.unstubAllGlobals());
  function mount(workspaceId = () => 'default') {
    let controller: ReturnType<typeof createLearningController>;
    const render = () => { document.body.innerHTML = learningPageHtml(controller.viewState()); controller.bind(); };
    controller = createLearningController({ render, workspaceId });
    return { controller, render };
  }
  it('exposes a native Settings route and escapes conversation evidence', () => {
    expect(settingsPageIdFromParams({ app_page: 'pages/learning' })).toBe('learning');
    const data = fixture();
    data.items.push({ id: 'candidate', kind: 'memory', title: '<script>alert(1)</script>', body: 'Fact', status: 'pending', occurrences: 1,
      node_id: '', provider_id: '', details: {}, evidence: [{ session_id: 'chat', turn_id: 'turn', role: 'user', quote: '<img src=x onerror=alert(1)>', metrics: {} }] });
    document.body.innerHTML = learningPageHtml({ data, error: '', loading: false, saving: false, tab: 'memory', detail: null, dependency: null, dirty: false });
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('img')).toBeNull();
    expect(document.body.textContent).toContain('<script>alert(1)</script>');
  });
  it('preserves unsaved Settings edits when changing tabs and saves their values', async () => {
    const { controller } = mount();
    await controller.load();
    const field = document.querySelector<HTMLInputElement>('[name=idle_seconds]')!;
    field.value = '300'; field.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector<HTMLButtonElement>('[data-learning-tab=analyses]')!.click();
    expect(document.querySelector<HTMLInputElement>('[name=idle_seconds]')!.value).toBe('300');
    expect(controller.viewState().dirty).toBe(true);
    document.querySelector<HTMLFormElement>('#learning-settings')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(controller.viewState().saving).toBe(false));
    const mutation = api.request.mock.calls.find(([, options]) => JSON.parse(options.body).action === 'learning.configure');
    expect(JSON.parse(mutation![1].body).settings.idle_seconds).toBe(300);
  });
  it('discards late responses when switching workspace', async () => {
    let workspace = 'first';
    let resolve!: (value: LearningData) => void;
    api.request.mockReturnValueOnce(new Promise<LearningData>((done) => { resolve = done; }));
    const { controller } = mount(() => workspace);
    const oldLoad = controller.load();
    workspace = 'second'; controller.reset();
    const second = fixture(); second.daily_tokens_reserved_or_used = 42;
    api.request.mockResolvedValueOnce(second);
    await controller.load();
    resolve(fixture()); await oldLoad;
    expect(controller.viewState().data?.daily_tokens_reserved_or_used).toBe(42);
  });
  it('keeps edited candidates through rerenders and emits explicit review actions', async () => {
    const data = fixture();
    data.items.push({ id: 'candidate', kind: 'memory', title: 'Original', body: 'Fact', status: 'pending', occurrences: 1,
      node_id: '', provider_id: '', details: {}, evidence: [] });
    api.request.mockResolvedValue(data);
    const { controller, render } = mount();
    await controller.load();
    const field = document.querySelector<HTMLInputElement>('[data-learning-title]')!;
    field.value = 'Edited'; field.dispatchEvent(new Event('input', { bubbles: true }));
    render();
    expect(document.querySelector<HTMLInputElement>('[data-learning-title]')!.value).toBe('Edited');
    document.querySelector<HTMLButtonElement>('[data-learning-command=edit]')!.click();
    await vi.waitFor(() => expect(controller.viewState().saving).toBe(false));
    const mutation = api.request.mock.calls.find(([, options]) => JSON.parse(options.body).action === 'learning.review');
    expect(JSON.parse(mutation![1].body)).toMatchObject({ item_id: 'candidate', command: 'edit', title: 'Edited' });
  });

  it('uses the shell event transport and refreshes results while preserving focused drafts', async () => {
    const { controller } = mount();
    await controller.load(); controller.setVisible(true);
    const field = document.querySelector<HTMLTextAreaElement>('[name=instructions]')!;
    field.value = 'Keep this draft'; field.focus(); field.setSelectionRange(3, 5);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    const changed = fixture(); changed.daily_tokens_reserved_or_used = 4200;
    api.request.mockResolvedValue(changed);
    events.subscribe.mock.calls[0][0]({ workspace_id: 'default', owner_app_id: 'chat', resource: 'learning' });
    await vi.waitFor(() => expect(controller.viewState().data?.daily_tokens_reserved_or_used).toBe(4200));
    expect(document.querySelector<HTMLTextAreaElement>('[name=instructions]')!.value).toBe('Keep this draft');
    expect(document.activeElement?.getAttribute('name')).toBe('instructions');
    expect((document.activeElement as HTMLTextAreaElement).selectionStart).toBe(3);
    controller.setVisible(false); expect(events.stop).toHaveBeenCalled();
  });

  it('refresh preserves drafts and discard explicitly clears them', async () => {
    const { controller } = mount(); await controller.load();
    const field = document.querySelector<HTMLInputElement>('[name=idle_seconds]')!;
    field.value = '300'; field.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector<HTMLButtonElement>('#learning-refresh')!.click();
    await vi.waitFor(() => expect(controller.viewState().loading).toBe(false));
    expect(document.querySelector<HTMLInputElement>('[name=idle_seconds]')!.value).toBe('300');
    document.querySelector<HTMLButtonElement>('#learning-discard')!.click();
    expect(document.querySelector<HTMLInputElement>('[name=idle_seconds]')!.value).toBe('120');
    expect(controller.viewState().dirty).toBe(false);
  });

  it('pause is independent of unsaved settings and selected chats survive rerenders', async () => {
    const data = fixture(); data.conversations.push({ session_id: 'chat-1', project_id: '', last_activity: 1, label: 'A useful chat' });
    api.request.mockResolvedValue(data);
    const { controller } = mount(); await controller.load();
    const field = document.querySelector<HTMLInputElement>('[name=idle_seconds]')!;
    field.value = '300'; field.dispatchEvent(new Event('input', { bubbles: true }));
    const select = document.querySelector<HTMLSelectElement>('#learning-session')!;
    select.value = 'chat-1'; select.dispatchEvent(new Event('change'));
    document.querySelector<HTMLButtonElement>('#learning-pause')!.click();
    await vi.waitFor(() => expect(controller.viewState().saving).toBe(false));
    expect(document.querySelector<HTMLInputElement>('[name=idle_seconds]')!.value).toBe('300');
    expect(document.querySelector<HTMLSelectElement>('#learning-session')!.value).toBe('chat-1');
    const mutation = api.request.mock.calls.find(([, options]) => JSON.parse(options.body).action === 'learning.configure');
    expect(JSON.parse(mutation![1].body).settings).toEqual({ paused: true });
  });

  it('rejects a pre-save read that arrives after the updated settings', async () => {
    const { controller } = mount(); await controller.load();
    let finishRead!: (value: LearningData) => void;
    api.request.mockReturnValueOnce(new Promise<LearningData>((done) => { finishRead = done; }));
    const staleRead = controller.load(true);
    const data = fixture(); data.settings.idle_seconds = 300;
    api.request.mockResolvedValue(data);
    const field = document.querySelector<HTMLInputElement>('[name=idle_seconds]')!;
    field.value = '300'; field.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector<HTMLFormElement>('#learning-settings')!.dispatchEvent(new Event('submit', { cancelable: true }));
    await vi.waitFor(() => expect(controller.viewState().saving).toBe(false));
    finishRead(fixture()); await staleRead;
    expect(controller.viewState().data?.settings.idle_seconds).toBe(300);
  });

  it('opens evidence on the platform origin from an isolated Settings frame', async () => {
    const data = fixture();
    data.items.push({ id: 'candidate', kind: 'memory', title: 'Preference', body: 'Fact', status: 'pending', occurrences: 1,
      node_id: '', provider_id: '', details: {}, evidence: [{ session_id: 'chat-1', turn_id: 'turn-1', role: 'user', quote: 'Quoted evidence', metrics: {} }] });
    api.request.mockResolvedValue(data);
    const parent = { postMessage: vi.fn() };
    const original = window;
    vi.stubGlobal('window', new Proxy(original, { get: (target, key) => key === 'parent' ? parent : key === '__MAVERICK_PLATFORM_ORIGIN__' ? 'https://maverick.test' : Reflect.get(target, key) }));
    const { controller } = mount(); await controller.load();
    document.querySelector<HTMLAnchorElement>('a[href^="/app/chat"]')!.click();
    expect(parent.postMessage).toHaveBeenCalledWith({ type: 'maverick.app.open-app', app_id: 'chat', params: { app_page: 'threads/chat-1' } }, 'https://maverick.test');
  });

  it('hides irrelevant model controls and supports keyboard tabs', async () => {
    const { controller } = mount(); await controller.load();
    const select = document.querySelector<HTMLSelectElement>('[name=model_source]')!;
    select.value = 'fast_model'; select.dispatchEvent(new Event('change', { bubbles: true }));
    expect(document.querySelector<HTMLElement>('[data-learning-native]')!.hidden).toBe(true);
    document.querySelector<HTMLButtonElement>('[data-learning-tab=memory]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    expect(controller.viewState().tab).toBe('improvements');
    expect(document.activeElement?.id).toBe('learning-tab-improvements');
  });

  it('does not display a late analysis detail after leaving its tab', async () => {
    const data = fixture();
    const job = { id: 'analysis-1', session_id: 'chat-1', status: 'completed', attempts: 1, created_at: 1, usage: 50, reserved: 100, error: '', model: '' };
    data.jobs.push(job); api.request.mockResolvedValue(data);
    const { controller } = mount(); await controller.load();
    document.querySelector<HTMLButtonElement>('[data-learning-tab=analyses]')!.click();
    let finish!: (value: { job: typeof job }) => void;
    api.request.mockReturnValueOnce(new Promise((done) => { finish = done; }));
    document.querySelector<HTMLButtonElement>('[data-learning-command=inspect]')!.click();
    document.querySelector<HTMLButtonElement>('[data-learning-tab=memory]')!.click();
    finish({ job }); await Promise.resolve();
    expect(controller.viewState().detail).toBeNull();
  });

  const proposal = (id: string, status = 'pending', implementation?: string) => ({ id, kind: 'improvement', title: `Fix ${id}`, body: 'A concrete problem', status, occurrences: 1,
    node_id: '', provider_id: '', details: { category: 'reliability', verification: 'Run the regression check' }, evidence: [{ session_id: 'source', turn_id: 'turn', role: 'user', quote: 'Evidence', metrics: {} }],
    ...(implementation ? { implementation: { status: implementation, session_id: `work-${id}`, turn_id: 'work-turn', error: '', summary: 'Regression passed', created_at: 1, updated_at: 1, attempt: 0 } } : {}) });

  it('places tickets in honest Kanban stages and keeps completed work behind the closed filter', async () => {
    const data = fixture();
    data.items = [proposal('proposed'), proposal('queued', 'accepted', 'queued'), proposal('active', 'accepted', 'running'), proposal('review', 'accepted', 'awaiting_review'), proposal('done', 'implemented', 'implemented')];
    api.request.mockResolvedValue(data);
    const { controller } = mount(); await controller.load();
    document.querySelector<HTMLButtonElement>('[data-learning-tab=improvements]')!.click();
    expect(document.querySelectorAll('.ticket-column')).toHaveLength(5);
    expect(document.querySelector('[data-ticket-column=review] [data-ticket-id=review]')).not.toBeNull();
    expect(document.querySelector('[data-ticket-id=done]')).toBeNull();
    expect(document.querySelector('[data-ticket-id=active] [data-learning-command=implemented]')).toBeNull();
    expect(document.querySelector('[data-ticket-id=review] [data-learning-command=implemented]')).not.toBeNull();
    document.querySelector<HTMLButtonElement>('[data-ticket-filter=closed]')!.click();
    expect(document.querySelector('[data-ticket-id=done]')).not.toBeNull();
    expect(document.querySelectorAll('[data-ticket-id]')).toHaveLength(1);
  });

  it('accept queues implementation and links to its normal Chat thread', async () => {
    const data = fixture(); data.items = [proposal('one')]; api.request.mockResolvedValue(data);
    const { controller } = mount(); await controller.load();
    document.querySelector<HTMLButtonElement>('[data-learning-tab=improvements]')!.click();
    data.items = [proposal('one', 'accepted', 'running')];
    document.querySelector<HTMLButtonElement>('[data-learning-command=accept]')!.click();
    await vi.waitFor(() => expect(controller.viewState().saving).toBe(false));
    const mutation = api.request.mock.calls.find(([, options]) => JSON.parse(options.body).command === 'accept');
    expect(JSON.parse(mutation![1].body)).toMatchObject({ action: 'learning.review', item_id: 'one', command: 'accept' });
    expect(document.querySelector('a[href="/app/chat/threads/work-one"]')?.textContent).toContain('Open work chat');
  });

  it('preserves ticket filters, search focus and horizontal scroll through live updates', async () => {
    const data = fixture(); data.items = [proposal('first'), proposal('second')]; api.request.mockResolvedValue(data);
    const { controller } = mount(); await controller.load(); controller.setVisible(true);
    document.querySelector<HTMLButtonElement>('[data-learning-tab=improvements]')!.click();
    const search = document.querySelector<HTMLInputElement>('#ticket-search')!;
    search.focus(); search.value = 'first'; search.setSelectionRange(2, 4); search.dispatchEvent(new Event('input'));
    expect(document.querySelectorAll('[data-ticket-id]')).toHaveLength(1);
    document.querySelector('.learning-kanban')!.scrollLeft = 320;
    events.subscribe.mock.calls[0][0]({ workspace_id: 'default', owner_app_id: 'chat', resource: 'learning' });
    await vi.waitFor(() => expect(controller.viewState().loading).toBe(false));
    expect(document.querySelector('.learning-kanban')!.scrollLeft).toBe(320);
    expect(document.activeElement?.id).toBe('ticket-search');
    expect((document.activeElement as HTMLInputElement).selectionStart).toBe(2);
    document.querySelector<HTMLButtonElement>('[data-ticket-view=list]')!.click();
    expect(document.querySelector('.learning-kanban')).toBeNull();
    expect(document.querySelectorAll('.ticket-list-row')).toHaveLength(1);
  });

  it('maps only authorized Kanban moves to commands and cannot invent runtime progress', () => {
    expect(ticketCommandForMove(proposal('first'), 'queued')).toBe('accept');
    expect(ticketCommandForMove(proposal('first'), 'running')).toBeUndefined();
    expect(ticketCommandForMove(proposal('active', 'accepted', 'running'), 'done')).toBeUndefined();
    expect(ticketCommandForMove(proposal('review', 'accepted', 'awaiting_review'), 'done')).toBe('implemented');
    expect(ticketCommandForMove(proposal('failed', 'accepted', 'failed'), 'queued')).toBe('retry');
  });

  it('uses the same Memory Kanban with explicit destination and separate project links', async () => {
    const data = fixture(); data.projects = { memory: 'memory-project', improvement: 'fix-project' };
    data.items = [{ ...proposal('fact'), kind: 'memory', provider_id: 'memory', details: { memory_matches: [{ id: 'existing', title: 'Existing fact' }] } }];
    api.request.mockResolvedValue(data);
    const { controller } = mount(); await controller.load();
    expect(document.querySelector('a[href="/app/chat/projects/memory-project"]')).not.toBeNull();
    const destination = document.querySelector<HTMLSelectElement>('[data-learning-target]')!;
    destination.value = 'existing'; destination.dispatchEvent(new Event('input'));
    document.querySelector<HTMLButtonElement>('[data-learning-command=approve]')!.click();
    await vi.waitFor(() => expect(controller.viewState().saving).toBe(false));
    const mutation = api.request.mock.calls.find(([, options]) => JSON.parse(options.body).command === 'approve');
    expect(JSON.parse(mutation![1].body)).toMatchObject({ action: 'learning.review', item_id: 'fact', target_node_id: 'existing' });
    document.querySelector<HTMLButtonElement>('[data-learning-tab=improvements]')!.click();
    expect(document.querySelector('a[href="/app/chat/projects/fix-project"]')).not.toBeNull();
  });

  it('keeps Memory and improvement filters independent when switching tabs', async () => {
    const data=fixture(); data.items=[{...proposal('fact'),kind:'memory',details:{category:'preference'}},proposal('fix')]; api.request.mockResolvedValue(data);
    const {controller}=mount(); await controller.load();
    const category=document.querySelector<HTMLSelectElement>('#ticket-category')!;
    category.value='preference'; category.dispatchEvent(new Event('change'));
    document.querySelector<HTMLButtonElement>('[data-learning-tab=improvements]')!.click();
    expect(document.querySelector('[data-ticket-id=fix]')).not.toBeNull();
    expect(document.querySelector<HTMLSelectElement>('#ticket-category')!.value).toBe('');
    document.querySelector<HTMLButtonElement>('[data-learning-tab=memory]')!.click();
    expect(document.querySelector<HTMLSelectElement>('#ticket-category')!.value).toBe('preference');
  });
});
