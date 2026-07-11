export function externalHttpUrlFromMessage(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  try {
    const url = new URL(value, window.location.origin);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.href;
  } catch {
    return null;
  }
}

export function openExternalUrl(url: string): void {
  const opened = window.open(url, "_blank", "noopener,noreferrer");
  if (opened) {
    try {
      opened.opener = null;
      opened.focus();
    } catch {
      // Cross-origin WindowProxy objects may reject focus/opener access.
    }
    return;
  }
  window.location.assign(url);
}
