/**
 * @vitest-environment happy-dom
 */
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fallbackMatchesForAppReference } from "../lib/messageReferenceMatches";
import type { AppReference, ChatMessage } from "../api/client";
import { ChatTranscript } from "./ChatTranscript";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(() => {
  root?.unmount();
  root = null;
  container?.remove();
  container = null;
});

function transcriptProps(conversationKey: string, messages: ChatMessage[]) {
  return {
    conversationKey,
    error: null,
    isLoading: false,
    loadingLabel: "",
    mentionItems: [],
    messages,
  };
}

function message(id: string, content: string): ChatMessage {
  return {
    id,
    role: "agent",
    content,
    createdAt: "2026-06-19T00:00:00Z",
  };
}

describe("chat transcript reference fallback matches", () => {
  it("matches entity references by stable ref marker when the label changed", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Renamed launch",
      summary: "server summary",
      deep_link: "/app/checklist/checklists/check_123",
    };

    expect(fallbackMatchesForAppReference("Review @Old launch [ref:checklist/checklist/check_123]", reference)).toEqual([
      {
        kind: "entity",
        id: "entity:checklist:checklist:check_123",
        appId: "checklist",
        entityType: "checklist",
        label: "Renamed launch",
        start: 7,
        end: 54,
        deepLink: "/app/checklist/checklists/check_123",
        summary: "server summary",
      },
    ]);
  });

  it("marks deleted entity references found by stable ref marker", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "missing",
      label: "missing",
      summary: "",
      exists: false,
    };

    expect(fallbackMatchesForAppReference("Review @Old launch [ref:checklist/checklist/missing]", reference)[0]).toMatchObject({
      kind: "entity",
      id: "entity:checklist:checklist:missing",
      label: "missing",
      exists: false,
    });
  });

  it("falls back to the marker range when the marker has no direct mention prefix", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Renamed launch",
    };

    expect(fallbackMatchesForAppReference("Compare @Chat\nthen [ref:checklist/checklist/check_123]", reference)).toEqual([
      {
        kind: "entity",
        id: "entity:checklist:checklist:check_123",
        appId: "checklist",
        entityType: "checklist",
        label: "Renamed launch",
        start: 19,
        end: 54,
      },
    ]);
  });

  it("does not consume plain app_id text before a marker", () => {
    const reference: AppReference = {
      type: "entity",
      app_id: "checklist",
      entity_type: "checklist",
      entity_id: "check_123",
      label: "Renamed launch",
    };

    expect(fallbackMatchesForAppReference("Compare app_id:chat then [ref:checklist/checklist/check_123]", reference)).toEqual([
      {
        kind: "entity",
        id: "entity:checklist:checklist:check_123",
        appId: "checklist",
        entityType: "checklist",
        label: "Renamed launch",
        start: 25,
        end: 60,
      },
    ]);
  });
});

describe("chat transcript scroll state", () => {
  it("resets to the bottom when the conversation key changes", async () => {
    const originalScrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return this.classList.contains("chatapp-chat-scroll__inner") ? 960 : 0;
      },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    try {
      await act(async () => {
        root?.render(createElement(ChatTranscript, transcriptProps("thread:first", [message("a", "First")])));
      });
      const viewport = container.querySelector(".chatapp-chat-scroll__inner") as HTMLDivElement | null;
      expect(viewport).not.toBeNull();
      if (!viewport) {
        return;
      }
      viewport.scrollTop = 120;

      await act(async () => {
        root?.render(createElement(ChatTranscript, transcriptProps("thread:second", [message("b", "Second")])));
      });

      expect(viewport.scrollTop).toBe(960);
      expect(container.querySelector(".chatapp-chat-scroll-jump")).toBeNull();
    } finally {
      if (originalScrollHeight) {
        Object.defineProperty(HTMLElement.prototype, "scrollHeight", originalScrollHeight);
      } else {
        delete (HTMLElement.prototype as { scrollHeight?: unknown }).scrollHeight;
      }
    }
  });

  it("keeps the bottom anchored when the composer overlay height changes", async () => {
    const originalScrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
      configurable: true,
      get() {
        return this.classList.contains("chatapp-chat-scroll__inner") ? 960 : 0;
      },
    });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    try {
      await act(async () => {
        root?.render(
          createElement(ChatTranscript, {
            ...transcriptProps("thread:first", [message("a", "First")]),
            composerOverlayHeight: 144,
          }),
        );
      });
      const viewport = container.querySelector(".chatapp-chat-scroll__inner") as HTMLDivElement | null;
      expect(viewport).not.toBeNull();
      if (!viewport) {
        return;
      }
      viewport.scrollTop = 420;

      await act(async () => {
        root?.render(
          createElement(ChatTranscript, {
            ...transcriptProps("thread:first", [message("a", "First")]),
            composerOverlayHeight: 320,
          }),
        );
      });

      expect(viewport.scrollTop).toBe(960);
      expect(container.querySelector(".chatapp-chat-scroll-jump")).toBeNull();
    } finally {
      if (originalScrollHeight) {
        Object.defineProperty(HTMLElement.prototype, "scrollHeight", originalScrollHeight);
      } else {
        delete (HTMLElement.prototype as { scrollHeight?: unknown }).scrollHeight;
      }
    }
  });
});

describe("chat transcript provider overload recovery", () => {
  it("offers continuation only for the latest recoverable failure", async () => {
    const onContinue = vi.fn();
    const overload: ChatMessage = {
      id: "overload",
      role: "system",
      content: "The model provider is temporarily overloaded.",
      createdAt: "2026-08-31T09:00:00Z",
      status: "failed",
      failureReasonCode: "provider_overloaded",
    };
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        createElement(ChatTranscript, {
          ...transcriptProps("thread:overloaded", [overload]),
          onContinueFromProviderOverload: onContinue,
        }),
      );
    });
    const button = container.querySelector(
      ".chatapp-system-update__action",
    ) as HTMLButtonElement | null;
    expect(button?.textContent).toContain("Continue");

    await act(async () => {
      button?.click();
    });
    expect(onContinue).toHaveBeenCalledTimes(1);

    await act(async () => {
      root?.render(
        createElement(ChatTranscript, {
          ...transcriptProps("thread:overloaded", [overload, message("answer", "Recovered")]),
          onContinueFromProviderOverload: onContinue,
        }),
      );
    });
    expect(container.querySelector(".chatapp-system-update__action")).toBeNull();
  });
});
