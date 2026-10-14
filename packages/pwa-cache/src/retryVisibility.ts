import { isExactLoopinoParentMessage } from "./dataCacheBrokerProtocol";

export class RetryVisibilityMonitor {
  private clientVisible = true;
  private started = false;

  constructor(
    private readonly documentVisible: () => boolean,
    private readonly onHint: () => void,
  ) {}

  visible(): boolean {
    return this.clientVisible && this.documentVisible() && globalThis.navigator?.onLine !== false;
  }

  setClientVisibility(visible: boolean): void {
    this.clientVisible = visible;
    if (visible) {
      this.onHint();
    }
  }

  start(): void {
    if (this.started || typeof window === "undefined") {
      return;
    }
    this.started = true;
    window.addEventListener("online", this.onHint);
    window.addEventListener("focus", this.onHint);
    window.addEventListener("message", this.handleLoopinoVisibility);
    globalThis.document?.addEventListener("visibilitychange", this.handleDocumentVisibility);
  }

  dispose(): void {
    if (this.started && typeof window !== "undefined") {
      window.removeEventListener("online", this.onHint);
      window.removeEventListener("focus", this.onHint);
      window.removeEventListener("message", this.handleLoopinoVisibility);
      globalThis.document?.removeEventListener("visibilitychange", this.handleDocumentVisibility);
    }
    this.started = false;
  }

  private readonly handleDocumentVisibility = () => {
    if (this.visible()) {
      this.onHint();
    }
  };

  private readonly handleLoopinoVisibility = (event: MessageEvent<unknown>) => {
    if (!isExactLoopinoParentMessage(event) || !event.data || typeof event.data !== "object") {
      return;
    }
    const payload = event.data as { type?: unknown; visible?: unknown };
    if (payload.type === "loopino.app.visibility-changed" && typeof payload.visible === "boolean") {
      this.setClientVisibility(payload.visible);
    }
  };
}
