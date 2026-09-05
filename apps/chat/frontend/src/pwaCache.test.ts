import { describe, expect, it, vi } from 'vitest';
import { sanitizeChatReadModel } from './pwaReadModel';
import { displayMessageEvents, displayThread, readChatDisplay } from './pwaCache';
const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock('@maverick/pwa-cache', async (original) => ({ ...await original<object>(), readAppCacheModel: mocks.read }));
describe('approved Chat persistence', () => {
  it('projects only completed display roles, never tool or runtime authority', () => {
    expect(sanitizeChatReadModel({ kind: 'messages', data: { activeSession: { secret: 1 }, messages: [
      { id: 'm', turn_id: 't', role: 'assistant', text: 'Answer', created_at: '2026-09-05', provider: 'secret' },
    ] } })).toEqual({ kind: 'messages', data: { messages: [{ id: 'm', turn_id: 't', role: 'assistant', text: 'Answer', created_at: '2026-09-05' }] } });
    expect(sanitizeChatReadModel({ kind: 'messages', data: { messages: [{ id:'m',turn_id:'t',role:'tool',text:'secret',created_at:'2026-09-05' }] } })).toBeNull();
    expect(sanitizeChatReadModel({ kind: 'threads', data: { threads: [{thread_id:null,runtime_session_id:'s',title:'x'}] } })).toBeNull();
  });
  it('renders history with completed markers but supplies no admission or pending send identity', () => {
    const events = displayMessageEvents('s', [{id:'m',turn_id:'t',role:'assistant',text:'Done',created_at:'2026-09-05'}]);
    expect(events.map((event) => event.event_type)).toEqual(['runtime.output.final','runtime.turn.completed']);
    expect(events.every((event) => event.event_id.startsWith('display:'))).toBe(true);
    expect(displayThread({ thread_id:'t' }).availability).toBe('unknown');
  });
  it('delivers warm display and changed revalidation without another dependency', async () => {
    const warm = { projects: [], has_more: false };
    mocks.read.mockResolvedValue({ payload: {kind:'projects',data:warm} });
    const changed = vi.fn();
    expect(await readChatDisplay({ kind:'projects',offset:0 },{ onRevalidated:changed })).toEqual(warm);
    mocks.read.mock.calls[0][2].onRevalidated({kind:'projects',data:{projects:[{project_id:'p',name:'New'}],has_more:false}});
    expect(changed).toHaveBeenCalledWith({projects:[{project_id:'p',name:'New'}],has_more:false});
  });
});
