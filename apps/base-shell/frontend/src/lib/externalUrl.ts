import { isStandaloneWebApp } from '@maverick/pwa-cache';

export type ExternalUrlDisposition = "new-window" | "same-window";

type ExternalUrlEffects = {
  assign: (url: string) => void;
  open: (url: string, target: string, features: string) => Window | null;
  nativeOpen?: (url: string) => Promise<void>;
  standalone?: boolean;
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

export async function openExternalUrl(
  url: string,
  disposition: ExternalUrlDisposition = "new-window",
  effects: ExternalUrlEffects = {
    assign: (target) => window.location.assign(target),
    open: (target, name, features) => window.open(target, name, features),
    nativeOpen: nativeExternalUrlOpener(),
  },
): Promise<void> {
  if (effects.nativeOpen) {
    try {
      await effects.nativeOpen(url);
      return;
    } catch {
      // A rejected native request can still use WebKit's navigation delegate.
    }
  }
  if (disposition === "same-window" || (effects.standalone ?? isStandaloneWebApp())) {
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

function nativeExternalUrlOpener(): ExternalUrlEffects["nativeOpen"] {
  const native = (window as unknown as {
    webkit?: { messageHandlers?: { maverickExternalURL?: { postMessage(value: unknown): Promise<unknown> } } };
  }).webkit?.messageHandlers?.maverickExternalURL;
  if (!native) return undefined;
  return async (url) => {
    if (await native.postMessage({ url }) !== true) {
      throw new Error("Native external URL request was refused.");
    }
  };
}
