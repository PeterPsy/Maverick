import { useEffect, useRef, useState, type FocusEvent, type PointerEvent, type RefObject } from "react";

export function useComposerInteraction(editorRef: RefObject<HTMLDivElement | null>) {
  const composerRef = useRef<HTMLElement | null>(null);
  const [isEditorExpanded, setIsEditorExpanded] = useState(false);

  useEffect(() => {
    function collapseOutsideComposer(event: Event) {
      const target = event.target;
      if (target instanceof Node && !composerRef.current?.contains(target)) {
        setIsEditorExpanded(false);
      }
    }
    document.addEventListener("pointerdown", collapseOutsideComposer, true);
    document.addEventListener("focusin", collapseOutsideComposer);
    return () => {
      document.removeEventListener("pointerdown", collapseOutsideComposer, true);
      document.removeEventListener("focusin", collapseOutsideComposer);
    };
  }, []);

  function onComposerFocus(event: FocusEvent<HTMLElement>) {
    if (event.target === editorRef.current) {
      setIsEditorExpanded(true);
    }
  }

  function onToolbarPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (document.activeElement === editorRef.current && event.target instanceof Element && event.target.closest("button")) {
      // Keep the editor selection and mobile keyboard until the action's click.
      // Search fields and native selects inside popups still receive normal focus.
      event.preventDefault();
    }
  }

  return { composerRef, isEditorExpanded, onComposerFocus, onToolbarPointerDown };
}
