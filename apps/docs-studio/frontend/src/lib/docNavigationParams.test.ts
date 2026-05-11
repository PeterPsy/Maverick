import { describe, expect, it } from 'vitest';
import { docPageIdFromParams, docPageIdFromWidgetContext } from './docNavigationParams';

describe('doc navigation params', () => {
  it('prefers explicit page_id', () => {
    expect(docPageIdFromParams({ app_page: 'pages/ignored', page_id: 'provider-credentials' })).toBe('provider-credentials');
  });

  it('extracts page id from app_page', () => {
    expect(docPageIdFromParams({ app_page: '/pages/core-overview/' })).toBe('core-overview');
  });

  it('extracts the active docs page from widget context', () => {
    expect(
      docPageIdFromWidgetContext({
        type: 'maverick.widget.context-changed',
        context: {
          content: {
            payload: {
              active_app_id: 'docs-studio',
              active_app_params: { app_page: 'pages/widgets' }
            }
          }
        }
      })
    ).toBe('widgets');
  });
});
