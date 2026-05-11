import { describe, expect, it, vi } from 'vitest';
import { docPageIdFromSelectionMessage, notifyActiveDocSelection } from './activeDocSelection';

describe('active doc selection', () => {
  it('posts normalized selection to the parent shell', () => {
    const postMessage = vi.fn();

    const didNotify = notifyActiveDocSelection('  core-overview  ', {
      currentWindow: {},
      origin: 'http://maverick.local',
      parentWindow: { postMessage }
    });

    expect(didNotify).toBe(true);
    expect(postMessage).toHaveBeenCalledWith(
      {
        type: 'maverick.app.selection-changed',
        owner_app_id: 'docs-studio',
        selection: { page_id: 'core-overview' }
      },
      'http://maverick.local'
    );
  });

  it('reads selected page ids from app selection messages', () => {
    expect(
      docPageIdFromSelectionMessage({
        type: 'maverick.app.selection-changed',
        owner_app_id: 'docs-studio',
        selection: { page_id: 'provider-credentials' }
      })
    ).toBe('provider-credentials');
  });
});
