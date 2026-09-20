export type CatalogCancellation = 'navigation' | 'refresh' | 'suspend' | 'dispose';
type Lane = string;

/** Owns one surface's reads. A cancelled transport can still deliver; the ticket fences it. */
export class StorageCatalogRequests {
  private generation = 0;
  private identity = '';
  private enabled = true;
  private readonly reads = new Map<Lane, CatalogRead>();

  transition(identity: string, reason: CatalogCancellation = 'navigation'): void {
    this.generation += 1;
    this.identity = identity;
    for (const read of this.reads.values()) read.controller.abort(reason);
    this.reads.clear();
  }

  start(lane: Lane): CatalogRead | null {
    if (!this.enabled || this.reads.has(lane)) return null;
    const generation = this.generation;
    const identity = this.identity;
    const controller = new AbortController();
    const read: CatalogRead = {
      controller,
      current: () => generation === this.generation && identity === this.identity
        && this.reads.get(lane) === read && !controller.signal.aborted,
      finish: () => { if (this.reads.get(lane) === read) this.reads.delete(lane); },
    };
    this.reads.set(lane, read);
    return read;
  }

  invalidate(reason: CatalogCancellation): void { this.transition(this.identity, reason); }

  dispose(): void { this.enabled = false; this.invalidate('dispose'); }

  replace(lane: Lane): CatalogRead | null {
    this.reads.get(lane)?.controller.abort('refresh');
    this.reads.delete(lane);
    return this.start(lane);
  }

  setVisible(visible: boolean): void {
    this.enabled = visible;
    if (!visible) this.invalidate('suspend');
  }
}

export type CatalogRead = {
  controller: AbortController;
  current(): boolean;
  finish(): void;
};
