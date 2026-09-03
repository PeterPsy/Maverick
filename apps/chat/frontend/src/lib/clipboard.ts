export async function copyTextToClipboard(content: string): Promise<boolean> {
  if (!content) {
    return false;
  }

  if (typeof navigator !== "undefined" && typeof navigator.clipboard?.writeText === "function") {
    try {
      await navigator.clipboard.writeText(content);
      return true;
    } catch {
      // Cross-origin app frames can expose the API while still denying writes.
    }
  }

  return copyTextWithDocumentCommand(content);
}

function copyTextWithDocumentCommand(content: string): boolean {
  if (
    typeof document === "undefined"
    || !document.body
    || typeof document.execCommand !== "function"
  ) {
    return false;
  }

  const activeElement = document.activeElement;
  const textarea = document.createElement("textarea");
  textarea.value = content;
  textarea.readOnly = true;
  textarea.tabIndex = -1;
  textarea.setAttribute("aria-hidden", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.append(textarea);

  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    textarea.remove();
    if (activeElement instanceof HTMLElement && activeElement.isConnected) {
      try {
        activeElement.focus({ preventScroll: true });
      } catch {
        try {
          activeElement.focus();
        } catch {
          // Restoring focus must not turn a successful copy into a failure.
        }
      }
    }
  }
}
