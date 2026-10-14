import { useLayoutEffect, useRef } from "react";
import { composerDraftKey, composerDraftStorage, readComposerDraft, writeComposerDraft } from "../lib/composerDrafts";

/** Restores editable text only, after live dependencies resolve the target chat. */
export function useChatDraftRecovery(options: {
  ready: boolean; workspaceId: string; navigationScope: string; conversationKey: string;
  composer: string; setComposer: (text: string) => void;
}) {
  const activeKey = useRef<string | null>(null);
  const key = options.ready && options.workspaceId && options.conversationKey
    ? composerDraftKey(options.workspaceId, options.navigationScope, options.conversationKey) : null;

  useLayoutEffect(() => {
    if (!key) return;
    const storage = composerDraftStorage();
    if (!storage) return;
    if (activeKey.current !== key) {
      activeKey.current = key;
      const saved = readComposerDraft(storage, key);
      if (!options.composer && saved !== null) {
        options.setComposer(saved);
        return;
      }
    }
    // Synchronous writes on every edit survive process termination without
    // relying on unload/background callbacks, which iOS may never deliver.
    writeComposerDraft(storage, key, options.composer);
  }, [key, options.composer, options.setComposer]);
}
