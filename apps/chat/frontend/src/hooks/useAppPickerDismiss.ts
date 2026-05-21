import { type Dispatch, type RefObject, type SetStateAction, useEffect } from "react";
import type { ActiveMention } from "../lib/mentions";

export function useAppPickerDismiss({
  activeAppMention,
  appPickerButtonRef,
  appPickerPanelRef,
  dismissedMentionStart,
  isOpen,
  setDismissedMentionStart,
  setShowAppPicker,
  showAppPicker,
  value,
}: {
  activeAppMention: ActiveMention | null;
  appPickerButtonRef: RefObject<HTMLButtonElement | null>;
  appPickerPanelRef: RefObject<HTMLDivElement | null>;
  dismissedMentionStart: number | null;
  isOpen: boolean;
  setDismissedMentionStart: Dispatch<SetStateAction<number | null>>;
  setShowAppPicker: Dispatch<SetStateAction<boolean>>;
  showAppPicker: boolean;
  value: string;
}) {
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || appPickerPanelRef.current?.contains(target) || appPickerButtonRef.current?.contains(target)) {
        return;
      }
      if (showAppPicker) {
        setShowAppPicker(false);
      } else if (activeAppMention) {
        setDismissedMentionStart(activeAppMention.start);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [activeAppMention, appPickerButtonRef, appPickerPanelRef, isOpen, setDismissedMentionStart, setShowAppPicker, showAppPicker]);

  useEffect(() => {
    if (dismissedMentionStart === null) {
      return;
    }
    const dismissedTrigger = value[dismissedMentionStart];
    if (dismissedTrigger !== "@" && dismissedTrigger !== "$") {
      setDismissedMentionStart(null);
    }
  }, [dismissedMentionStart, setDismissedMentionStart, value]);
}
