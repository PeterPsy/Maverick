import { Dispatch, SetStateAction, useEffect } from "react";
import type { AppDependenciesPayload } from "../api/client";
import { ActiveAppContext, activeAppContextFromWidgetContext } from "../lib/activeAppContext";
import { shellMessageMatchesNavigationScope } from "../lib/shellNavigation";

type ShellNavigationMessage = {
  type?: string;
  context?: Record<string, unknown>;
  error?: string;
  files?: unknown[];
  dependencies?: AppDependenciesPayload;
  navigation_scope?: string;
  owner_app_id?: string;
  app_id?: string;
  params?: Record<string, string | boolean | null>;
  resource?: string;
};

type UseChatShellMessagesParams = {
  addAttachments: (files: File[]) => void;
  agentCatalogAppId: string;
  loadAgentOptionsFromDependencies: (dependencies: AppDependenciesPayload) => Promise<void>;
  loadAppDependencies: () => Promise<void>;
  loadSpeechProviderFromDependencies: (dependencies: AppDependenciesPayload) => Promise<void>;
  loadTranscriptionProviderFromDependencies: (dependencies: AppDependenciesPayload) => Promise<void>;
  navigationScope: string;
  onNavigate: (params: Record<string, string | boolean | null>) => Promise<void>;
  setActiveAppContext: Dispatch<SetStateAction<ActiveAppContext | null>>;
  setComposerError: Dispatch<SetStateAction<string | null>>;
  speechProviderAppId: string;
  transcriptionProviderAppId: string;
};

export function useChatShellMessages({
  addAttachments,
  agentCatalogAppId,
  loadAgentOptionsFromDependencies,
  loadAppDependencies,
  loadSpeechProviderFromDependencies,
  loadTranscriptionProviderFromDependencies,
  navigationScope,
  onNavigate,
  setActiveAppContext,
  setComposerError,
  speechProviderAppId,
  transcriptionProviderAppId,
}: UseChatShellMessagesParams) {
  useEffect(() => {
    window.parent?.postMessage({ type: "maverick.app.ready", app_id: "chat" }, window.location.origin);
  }, []);

  useEffect(() => {
    function handleShellMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const payload = event.data as ShellNavigationMessage;
      if (payload.type === "maverick.widget.capture-area.complete") {
        if (!shellMessageMatchesNavigationScope(payload, navigationScope)) {
          return;
        }
        const files = Array.isArray(payload.files) ? payload.files.filter((file): file is File => file instanceof File) : [];
        if (files.length) {
          addAttachments(files);
          setComposerError(null);
        }
        return;
      }
      if (payload.type === "maverick.widget.capture-area.error") {
        if (!shellMessageMatchesNavigationScope(payload, navigationScope)) {
          return;
        }
        setComposerError(payload.error || "Unable to capture page area.");
        return;
      }
      if (payload.type === "maverick.widget.context-changed") {
        // Unlike app-navigation messages, widget context keeps the scope under
        // context.content.payload. Read it there so a dock receives its live
        // Design Studio project without leaking context between chat surfaces.
        if (!shellMessageMatchesNavigationScope(
          { navigation_scope: widgetContextNavigationScope(payload.context) },
          navigationScope,
        )) {
          return;
        }
        setActiveAppContext(activeAppContextFromWidgetContext(payload.context || {}));
        return;
      }
      if (payload.type === "maverick.app.dependencies" && payload.app_id === "chat" && payload.dependencies) {
        void Promise.all([
          loadAgentOptionsFromDependencies(payload.dependencies),
          loadSpeechProviderFromDependencies(payload.dependencies),
          loadTranscriptionProviderFromDependencies(payload.dependencies),
        ]);
        return;
      }
      if (
        payload.type === "maverick.app.data-changed" &&
        payload.resource === "configuration" &&
        (payload.owner_app_id === agentCatalogAppId || payload.owner_app_id === speechProviderAppId || payload.owner_app_id === transcriptionProviderAppId)
      ) {
        void loadAppDependencies();
        return;
      }
      if (!shellMessageMatchesNavigationScope(payload, navigationScope)) {
        return;
      }
      if (payload.type !== "maverick.app.navigate" || (payload.app_id && payload.app_id !== "chat")) {
        return;
      }
      void onNavigate(payload.params || {});
    }

    window.addEventListener("message", handleShellMessage);
    return () => window.removeEventListener("message", handleShellMessage);
  }, [
    addAttachments,
    agentCatalogAppId,
    loadAgentOptionsFromDependencies,
    loadAppDependencies,
    loadSpeechProviderFromDependencies,
    loadTranscriptionProviderFromDependencies,
    navigationScope,
    onNavigate,
    setActiveAppContext,
    setComposerError,
    speechProviderAppId,
    transcriptionProviderAppId,
  ]);
}

function widgetContextNavigationScope(context: Record<string, unknown> | undefined): string | undefined {
  const content = context?.content;
  if (!content || typeof content !== "object") {
    return undefined;
  }
  const payload = (content as { payload?: unknown }).payload;
  if (!payload || typeof payload !== "object") {
    return undefined;
  }
  const scope = (payload as { navigation_scope?: unknown }).navigation_scope;
  return typeof scope === "string" ? scope : undefined;
}
