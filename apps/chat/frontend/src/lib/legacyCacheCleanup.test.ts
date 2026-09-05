// @vitest-environment happy-dom
import { expect, it } from 'vitest';
import { purgeLegacyChatCaches } from './legacyCacheCleanup';
it('deletes unscoped history, projects and deferred sends without importing them', () => {
  for (const storage of [localStorage, sessionStorage]) {
    storage.setItem('maverick.chat.queued-messages.v1:private', 'untrusted');
    storage.setItem('maverick.chat.runtime-transcript-cache.v2:private', 'untrusted');
    storage.setItem('maverick.chat.projects-cache.v1:private', 'untrusted');
    storage.setItem('unrelated', 'preserved');
  }
  purgeLegacyChatCaches();
  for (const storage of [localStorage, sessionStorage]) {
    expect(storage.getItem('maverick.chat.queued-messages.v1:private')).toBeNull();
    expect(storage.getItem('maverick.chat.runtime-transcript-cache.v2:private')).toBeNull();
    expect(storage.getItem('maverick.chat.projects-cache.v1:private')).toBeNull();
    expect(storage.getItem('unrelated')).toBe('preserved');
  }
});
