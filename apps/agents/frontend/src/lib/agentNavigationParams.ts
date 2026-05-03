export type AgentNavigationParams = Record<string, string | boolean | null | undefined>;

export type WidgetContextMessage = {
  context?: {
    content?: {
      payload?: unknown;
    };
  };
  type?: string;
};

export function scalarString(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

export function agentTypeIdFromParams(params: AgentNavigationParams): string {
  const directAgentTypeId = scalarString(params.agent_type_id);
  if (directAgentTypeId) {
    return directAgentTypeId;
  }
  const appPage = scalarString(params.app_page);
  const match = /^agent-types\/([^/]+)$/.exec(appPage);
  return match?.[1] || '';
}

export function shouldOpenNewAgent(params: AgentNavigationParams): boolean {
  return params.new_agent === true || params.new_agent === '1' || params.new_agent === 'true';
}

export function agentTypeIdFromWidgetContext(message: WidgetContextMessage): string {
  if (message.type !== 'maverick.widget.context-changed') {
    return '';
  }
  const payload = message.context?.content?.payload;
  if (!payload || typeof payload !== 'object') {
    return '';
  }
  const activeAppId = scalarString((payload as { active_app_id?: unknown }).active_app_id);
  if (activeAppId !== 'agents') {
    return '';
  }
  const activeAppParams = (payload as { active_app_params?: unknown }).active_app_params;
  if (!activeAppParams || typeof activeAppParams !== 'object' || Array.isArray(activeAppParams)) {
    return '';
  }
  return agentTypeIdFromParams(activeAppParams as AgentNavigationParams);
}
