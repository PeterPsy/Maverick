// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createLearningController, type LearningData } from './learningController';
import { learningPageHtml } from './learningPage';
import { settingsPageIdFromParams } from './pages';

const api = vi.hoisted(() => ({ request: vi.fn(), dependencies: vi.fn(), select: vi.fn() }));
vi.mock('./adminApi', () => ({ requestJson: api.request, getAppDependencies: api.dependencies, saveAppDependencySelection: api.select }));
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
    document.body.innerHTML = '';
  });
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
});
