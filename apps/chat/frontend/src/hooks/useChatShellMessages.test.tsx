/**
 * @vitest-environment happy-dom
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChatShellMessages } from "./useChatShellMessages";

describe("Chat shell context messages", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  it("applies a live widget project update to a scoped floating chat", async () => {
    const setActiveAppContext = vi.fn();

    function Harness() {
      useChatShellMessages({
        addAttachments: vi.fn(),
        agentCatalogAppId: "agents",
        loadAgentOptionsFromDependencies: async () => undefined,
        loadAppDependencies: async () => undefined,
        loadSpeechProviderFromDependencies: async () => undefined,
        loadTranscriptionProviderFromDependencies: async () => undefined,
        navigationScope: "chat-floating-dock",
        onNavigate: async () => undefined,
        setActiveAppContext,
        setComposerError: vi.fn(),
        speechProviderAppId: "speech",
        transcriptionProviderAppId: "speech",
      });
      return null;
    }

    await act(async () => root.render(<Harness />));
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          type: "maverick.widget.context-changed",
          owner_app_id: "chat",
          widget_id: "chat-floating-dock",
          context: {
            content: {
              payload: {
                active_app: {
                  app_id: "design-studio",
                  description: "Design workspace",
                  name: "Design Studio",
                  params: { od_project_id: "od_project_live" },
                  views: [],
                },
                navigation_scope: "chat-floating-dock",
              },
            },
          },
        },
        origin: window.location.origin,
      }));
    });

    expect(setActiveAppContext).toHaveBeenCalledWith({
      app_id: "design-studio",
      description: "Design workspace",
      name: "Design Studio",
      params: { od_project_id: "od_project_live" },
      views: [],
    });

    setActiveAppContext.mockClear();
    await act(async () => {
      window.dispatchEvent(new MessageEvent("message", {
        data: {
          type: "maverick.widget.context-changed",
          context: {
            content: {
              payload: {
                active_app: {
                  app_id: "design-studio",
                  description: "Other workspace",
                  name: "Design Studio",
                  params: { od_project_id: "od_project_other" },
                  views: [],
                },
                navigation_scope: "another-chat-surface",
              },
            },
          },
        },
        origin: window.location.origin,
      }));
    });

    expect(setActiveAppContext).not.toHaveBeenCalled();
  });
});
