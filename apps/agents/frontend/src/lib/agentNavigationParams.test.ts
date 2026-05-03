import { describe, expect, it } from 'vitest';
import { agentTypeIdFromParams, agentTypeIdFromWidgetContext, shouldOpenNewAgent } from './agentNavigationParams';

describe('agent navigation params', () => {
  it('extracts agent type ids from direct params and app pages', () => {
    expect(agentTypeIdFromParams({ agent_type_id: ' agent-type-a ' })).toBe('agent-type-a');
    expect(agentTypeIdFromParams({ app_page: 'agent-types/agent-type-b' })).toBe('agent-type-b');
    expect(agentTypeIdFromParams({ app_page: 'roles/role-a' })).toBe('');
  });

  it('normalizes new agent requests from shell navigation params', () => {
    expect(shouldOpenNewAgent({ new_agent: true })).toBe(true);
    expect(shouldOpenNewAgent({ new_agent: 'true' })).toBe(true);
    expect(shouldOpenNewAgent({ new_agent: '1' })).toBe(true);
    expect(shouldOpenNewAgent({ new_agent: false })).toBe(false);
  });

  it('hydrates the shell sidebar selection from widget context for active Agents routes', () => {
    expect(
      agentTypeIdFromWidgetContext({
        type: 'maverick.widget.context-changed',
        context: {
          content: {
            payload: {
              active_app_id: 'agents',
              active_app_params: { app_page: 'agent-types/agent-type-deep-link' }
            }
          }
        }
      })
    ).toBe('agent-type-deep-link');
  });

  it('ignores widget context for other active apps', () => {
    expect(
      agentTypeIdFromWidgetContext({
        type: 'maverick.widget.context-changed',
        context: {
          content: {
            payload: {
              active_app_id: 'chat',
              active_app_params: { app_page: 'agent-types/agent-type-a' }
            }
          }
        }
      })
    ).toBe('');
  });
});
