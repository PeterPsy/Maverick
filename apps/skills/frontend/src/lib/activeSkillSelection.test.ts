import { describe, expect, it } from 'vitest';
import { notifyActiveSkillSelection, skillIdFromSelectionMessage, skillIdFromWidgetContext } from './activeSkillSelection';

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

describe('active skill selection messages', () => {
  it('notifies shell-hosted widgets using the shared selection protocol', () => {
    const parent = messageTarget();

    const posted = notifyActiveSkillSelection(' skill-a ', {
      currentWindow: {},
      origin: 'https://maverick.test',
      parentWindow: parent.target
    });

    expect(posted).toBe(true);
    expect(parent.messages).toEqual([
      {
        message: {
          type: 'maverick.app.selection-changed',
          owner_app_id: 'skills',
          selection: { skill_id: 'skill-a' }
        },
        targetOrigin: 'https://maverick.test'
      }
    ]);
  });

  it('ignores empty selections and direct non-shell renders', () => {
    const parent = messageTarget();
    const currentWindow = {};

    expect(notifyActiveSkillSelection(' ', { currentWindow, parentWindow: parent.target })).toBe(false);
    expect(notifyActiveSkillSelection('skill-a', { currentWindow, parentWindow: currentWindow as never })).toBe(false);
    expect(parent.messages).toEqual([]);
  });

  it('extracts only Skills-owned active selections', () => {
    expect(
      skillIdFromSelectionMessage({
        type: 'maverick.app.selection-changed',
        owner_app_id: 'skills',
        selection: { skill_id: ' skill-a ' }
      })
    ).toBe('skill-a');
    expect(
      skillIdFromSelectionMessage({
        type: 'maverick.app.selection-changed',
        owner_app_id: 'agents',
        selection: { skill_id: 'skill-a' }
      })
    ).toBe('');
    expect(skillIdFromSelectionMessage({ type: 'maverick.widget.data-changed', owner_app_id: 'skills' })).toBe('');
  });

  it('reads the active skill from shell sidebar widget context', () => {
    expect(
      skillIdFromWidgetContext({
        type: 'maverick.widget.context-changed',
        context: {
          content: {
            payload: {
              active_app_params: { skill_id: ' skill-context ' }
            }
          }
        }
      })
    ).toBe('skill-context');
    expect(
      skillIdFromWidgetContext({
        context: {
          content: {
            payload: {
              active_app_params: { app_page: 'skills/skill-from-page' }
            }
          }
        }
      })
    ).toBe('skill-from-page');
  });
});
