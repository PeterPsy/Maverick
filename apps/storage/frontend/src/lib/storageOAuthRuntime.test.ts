import { describe, expect, it } from 'vitest';
import { storageOAuthCallbackFromLocation, storageOAuthRedirectUri } from './storageOAuthRuntime';

describe('storage OAuth runtime helpers', () => {
  it('builds the mounted Storage OAuth callback URL for the active app id', () => {
    expect(storageOAuthRedirectUri('storage-fork', 'https://maverick.local/')).toBe(
      'https://maverick.local/apps/storage-fork/oauth/callback',
    );
  });

  it('parses Google Drive OAuth callback parameters from the mounted app route', () => {
    expect(
      storageOAuthCallbackFromLocation(
        '/apps/storage-fork/oauth/callback',
        '?code=auth-code&state=drive-state',
        'https://maverick.local',
      ),
    ).toEqual({
      appId: 'storage-fork',
      code: 'auth-code',
      error: '',
      redirectUri: 'https://maverick.local/apps/storage-fork/oauth/callback',
      state: 'drive-state',
    });
  });

  it('ignores non-callback routes', () => {
    expect(storageOAuthCallbackFromLocation('/apps/storage/', '?code=auth-code', 'https://maverick.local')).toBeNull();
  });
});
