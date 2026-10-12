// Rebinding retained controls must replace their handlers, never accumulate them.
let bindings = new AbortController();

export function beginSettingsBindings() {
  bindings.abort();
  bindings = new AbortController();
}

export function bindControl<K extends keyof HTMLElementEventMap>(
  element: Element | null | undefined,
  type: K,
  handler: (event: HTMLElementEventMap[K]) => void,
) {
  element?.addEventListener(type, handler as EventListener, { signal: bindings.signal });
}
