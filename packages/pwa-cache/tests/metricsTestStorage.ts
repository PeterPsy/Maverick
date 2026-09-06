export class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();
  get length(): number { return this.values.size; }
  clear(): void { this.values.clear(); }
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  key(index: number): string | null { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string): void { this.values.delete(key); }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  serializedValues(): string { return [...this.values.values()].join("\n"); }
  writerKeys(): string[] { return [...this.values.keys()].filter((key) => key.includes(":writer:")); }
}

export class ResetInterleavingStorage extends MemoryStorage {
  afterResetRead: (() => void) | null = null;
  afterResetMarker: (() => void) | null = null;

  override getItem(key: string): string | null {
    const value = super.getItem(key);
    if (!key.endsWith(":reset") || !this.afterResetRead) return value;
    const callback = this.afterResetRead;
    this.afterResetRead = null;
    callback();
    return value;
  }

  override setItem(key: string, value: string): void {
    super.setItem(key, value);
    if (!key.endsWith(":reset") || !this.afterResetMarker) return;
    const callback = this.afterResetMarker;
    this.afterResetMarker = null;
    callback();
  }
}

