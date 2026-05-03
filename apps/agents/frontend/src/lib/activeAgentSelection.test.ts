import { describe, expect, it } from 'vitest';
import { agentTypeIdFromSelectionMessage, notifyActiveAgentSelection } from './activeAgentSelection';

function messageTarget() {
  const messages: Array<{ message: unknown; targetOrigin: string }> = [];
  return {
    messages,
    target: {
      postMessage(message: unknown, targetOrigin: string) {
        messages.push({ message, targetOrigin });
      }
    }
  };
}

describe('active agent selection messages', () => {
  it('notifies shell-hosted widgets when the main app changes active agent', () => {
    const parent = messageTarget();

    const posted = notifyActiveAgentSelection(' agent-type-server-coding-engineer ', {
      currentWindow: {},
      origin: 'https://maverick.test',
      parentWindow: parent.target
    });

    expect(posted).toBe(true);
    expect(parent.messages).toEqual([
      {
        message: {
          type: 'maverick.app.selection-changed',
          owner_app_id: 'agents',
          selection: { agent_type_id: 'agent-type-server-coding-engineer' }
        },
        targetOrigin: 'https://maverick.test'
      }
    ]);
  });

  it('ignores empty selections and direct non-shell renders', () => {
    const parent = messageTarget();
    const currentWindow = {};

    expect(notifyActiveAgentSelection(' ', { currentWindow, parentWindow: parent.target })).toBe(false);
    expect(notifyActiveAgentSelection('agent-type-a', { currentWindow, parentWindow: currentWindow as never })).toBe(false);
    expect(parent.messages).toEqual([]);
  });

  it('extracts only Agents-owned active agent selections', () => {
    expect(
      agentTypeIdFromSelectionMessage({
        type: 'maverick.app.selection-changed',
        owner_app_id: 'agents',
        selection: { agent_type_id: ' agent-type-a ' }
      })
    ).toBe('agent-type-a');
    expect(
      agentTypeIdFromSelectionMessage({
        type: 'maverick.app.selection-changed',
        owner_app_id: 'chat',
        selection: { agent_type_id: 'agent-type-a' }
      })
    ).toBe('');
    expect(agentTypeIdFromSelectionMessage({ type: 'maverick.widget.data-changed', owner_app_id: 'agents' })).toBe('');
  });
});
