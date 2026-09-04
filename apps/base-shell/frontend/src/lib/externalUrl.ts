export type ExternalUrlDisposition = "new-window" | "same-window";

type ExternalUrlEffects = {
  assign: (url: string) => void;
  open: (url: string, target: string, features: string) => Window | null;
};

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

export function externalUrlDispositionFromMessage(value: unknown): ExternalUrlDisposition {
  return value === "same-window" ? "same-window" : "new-window";
}

export function openExternalUrl(
  url: string,
  disposition: ExternalUrlDisposition = "new-window",
  effects: ExternalUrlEffects = {
    assign: (target) => window.location.assign(target),
    open: (target, name, features) => window.open(target, name, features),
  },
): void {
  if (disposition === "same-window") {
    effects.assign(url);
    return;
  }
  const opened = effects.open(url, "_blank", "noopener,noreferrer");
  if (opened) {
    try {
      opened.opener = null;
      opened.focus();
    } catch {
      // Cross-origin WindowProxy objects may reject focus/opener access.
    }
    return;
  }
  effects.assign(url);
}
