type ShellPostTarget = {
  postMessage: (message: unknown, targetOrigin: string) => void;
};

type NotifyOptions = {
  currentWindow?: unknown;
  origin?: string;
  parentWindow?: ShellPostTarget | null;
};

export type ActiveAgentSelectionMessage = {
  owner_app_id?: string;
  selection?: Record<string, unknown>;
  type?: string;
};

export function notifyActiveAgentSelection(agentTypeId: string, options: NotifyOptions = {}): boolean {
  const normalizedAgentTypeId = agentTypeId.trim();
  if (!normalizedAgentTypeId) {
    return false;
  }
  const currentWindow = options.currentWindow ?? (typeof window === 'undefined' ? null : window);
  const parentWindow = options.parentWindow ?? (typeof window === 'undefined' ? null : window.parent);
  if (!parentWindow || parentWindow === currentWindow) {
    return false;
  }
  const origin = options.origin ?? '*';
  parentWindow.postMessage(
    {
      type: 'maverick.app.selection-changed',
      owner_app_id: 'agents',
      selection: { agent_type_id: normalizedAgentTypeId }
    },
    origin
  );
  return true;
}

export function agentTypeIdFromSelectionMessage(message: ActiveAgentSelectionMessage, ownerAppId = 'agents'): string {
  if (message.type !== 'maverick.app.selection-changed' || message.owner_app_id !== ownerAppId) {
    return '';
  }
  const selection = message.selection;
  const value = selection && typeof selection.agent_type_id === 'string' ? selection.agent_type_id.trim() : '';
  return value;
}
