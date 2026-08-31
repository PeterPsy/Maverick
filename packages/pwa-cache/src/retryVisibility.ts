export class RetryVisibilityMonitor {
  private clientVisible = true;
  private started = false;

  constructor(
    private readonly documentVisible: () => boolean,
    private readonly onHint: () => void,
  ) {}

  visible(): boolean {
    return this.clientVisible && this.documentVisible();
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
    window.addEventListener("message", this.handleMaverickVisibility);
    document.addEventListener("visibilitychange", this.handleDocumentVisibility);
  }

  dispose(): void {
    if (this.started && typeof window !== "undefined") {
      window.removeEventListener("online", this.onHint);
      window.removeEventListener("focus", this.onHint);
      window.removeEventListener("message", this.handleMaverickVisibility);
      document.removeEventListener("visibilitychange", this.handleDocumentVisibility);
    }
    this.started = false;
  }

  private readonly handleDocumentVisibility = () => {
    if (this.visible()) {
      this.onHint();
    }
  };

  private readonly handleMaverickVisibility = (event: MessageEvent<unknown>) => {
    if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
      return;
    }
    const payload = event.data as { type?: unknown; visible?: unknown };
    if (payload.type === "maverick.app.visibility-changed" && typeof payload.visible === "boolean") {
      this.setClientVisibility(payload.visible);
    }
  };
}
