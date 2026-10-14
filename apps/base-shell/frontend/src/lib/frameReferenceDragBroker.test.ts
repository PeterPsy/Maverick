// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setLoopinoFrameOrigin } from '../iframePolicy';
import { installFrameReferenceDragBroker } from './frameReferenceDragBroker';

describe('isolated reference drag broker', () => {
  const scope = { workspaceId: 'fixture', sessionGeneration: 'login' };
  let source: HTMLIFrameElement;
  let target: HTMLIFrameElement;
  let stop: () => void;
  let hitTest: ReturnType<typeof vi.fn>;
  const transfer = { type: 'application/x-loopino-mail-thread', data: '{"thread_id":"fixture"}' };
  function frame(origin: string, left: number) {
    const element = document.createElement('iframe');
    document.body.append(element);
    setLoopinoFrameOrigin(element, origin, 'fixture-app', scope);
    for (const [name, value] of Object.entries({ clientLeft: 0, clientTop: 0, clientWidth: 400, clientHeight: 600, offsetWidth: 400, offsetHeight: 600 })) {
      Object.defineProperty(element, name, { value });
    }
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({ left, top: 0, x: left, y: 0, width: 400, height: 600, right: left + 400, bottom: 600, toJSON() {} });
    return element;
  }
  function send(type: string, overrides = {}, from = source, origin = from.dataset.loopinoFrameOrigin!) {
    window.dispatchEvent(new MessageEvent('message', {
      source: from.contentWindow, origin,
      data: { type: `loopino.reference-drag.${type}`, drag_id: 'drag-1', x: 500, y: 150,
        viewport_width: 400, viewport_height: 600, label: 'Email', transfer, ...overrides },
    }));
  }
  beforeEach(() => {
    source = frame('https://mail.example', 0);
    target = frame('https://chat.example', 400);
    hitTest = vi.fn(() => target);
    Object.defineProperty(document, 'elementFromPoint', { configurable: true, value: hitTest });
    stop = installFrameReferenceDragBroker(scope);
  });
  afterEach(() => {
    stop();
    for (const element of [source, target]) { setLoopinoFrameOrigin(element, null, 'fixture-app', scope); element.remove(); }
    vi.restoreAllMocks();
  });
  it('routes one drop to the hit frame using target-local coordinates and its exact origin', () => {
    const post = vi.spyOn(target.contentWindow!, 'postMessage');
    send('start'); send('end'); send('end');
    expect(hitTest).toHaveBeenCalledWith(500, 150);
    expect(post.mock.calls.filter(([message]) => message.type === 'loopino.reference-drag.drop')).toEqual([
      [{ type: 'loopino.reference-drag.drop', drag_id: 'drag-1', transfer, x: 100, y: 150 }, 'https://chat.example'],
    ]);
    expect(document.querySelector('.bs-reference-drag-preview')).toBeNull();
  });
  it('rejects forged origins, other sources, and stale workspace/session identities', () => {
    const post = vi.spyOn(target.contentWindow!, 'postMessage');
    send('start', {}, source, 'https://attacker.example'); send('end');
    send('start'); send('end', {}, target);
    setLoopinoFrameOrigin(source, 'https://mail.example', 'fixture-app', { ...scope, sessionGeneration: 'old-login' });
    send('end');
    expect(post.mock.calls.some(([message]) => message.type === 'loopino.reference-drag.drop')).toBe(false);
  });
  it('cancels without a drop and ignores malformed data or coordinates', () => {
    const post = vi.spyOn(target.contentWindow!, 'postMessage');
    send('start'); send('cancel'); send('end');
    send('start', { transfer: { type: 'text/html', data: 'bad' } }); send('end');
    send('start', { x: Infinity }); send('end');
    expect(post.mock.calls.some(([message]) => message.type === 'loopino.reference-drag.drop')).toBe(false);
  });
  it('sends hover and leave only to the visible scoped frame and clears hover on cancellation', () => {
    const targetPost = vi.spyOn(target.contentWindow!, 'postMessage');
    const sourcePost = vi.spyOn(source.contentWindow!, 'postMessage');
    send('start');
    hitTest.mockReturnValue(source);
    send('move', { x: 120 });
    send('cancel');
    expect(targetPost.mock.calls.map(([message]) => message.type)).toEqual([
      'loopino.reference-drag.over', 'loopino.reference-drag.leave',
    ]);
    expect(sourcePost.mock.calls.map(([message]) => message.type)).toEqual([
      'loopino.reference-drag.over', 'loopino.reference-drag.leave', 'loopino.reference-drag.finished',
    ]);
  });
  it('does not drop onto shell chrome or a frame from a different workspace', () => {
    const post = vi.spyOn(target.contentWindow!, 'postMessage');
    hitTest.mockReturnValue(document.body);
    send('start'); send('end');
    hitTest.mockReturnValue(target);
    setLoopinoFrameOrigin(target, 'https://chat.example', 'fixture-app', { ...scope, workspaceId: 'other' });
    send('start'); send('end');
    expect(post).not.toHaveBeenCalled();
  });
});
