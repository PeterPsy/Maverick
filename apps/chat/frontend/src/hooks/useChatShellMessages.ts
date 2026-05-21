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
        if (!shellMessageMatchesNavigationScope(payload, navigationScope)) {
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
