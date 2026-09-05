import { matchesFilter } from "./scope";
import { PWA_CACHE_ENTRY_SCHEMA_VERSION } from "./types";
import type {
  CacheBackend,
  CacheEntryMetadata,
  CacheFilter,
  CleanupMarker,
  StoredCacheEntry,
} from "./types";

export const PWA_CACHE_DATABASE_NAME = "maverick-pwa-data-v1";
export const PWA_CACHE_DATABASE_VERSION = 3;

const ENTRY_STORE = "entries";
const PAYLOAD_STORE = "payloads";
const METADATA_STORE = "metadata";

type PayloadRecord = { key: string; payload: unknown };
type MigrationStep = "create-v1" | "split-payloads-v2" | "create-indices-v2" | "resource-schema-v3";

export type IndexedDbCacheBackendOptions = {
  databaseName?: string;
  factory?: IDBFactory;
  migrationHook?: (step: MigrationStep) => void;
  now?: () => number;
};

export class IndexedDbCacheBackend implements CacheBackend {
  private readonly databaseName: string;
  private readonly factory: IDBFactory;
  private readonly migrationHook?: (step: MigrationStep) => void;
  private readonly now: () => number;
  private databasePromise: Promise<IDBDatabase> | null = null;
  private initialized = false;

  constructor(options: IndexedDbCacheBackendOptions = {}) {
    const factory = options.factory ?? globalThis.indexedDB;
    if (!factory) {
      throw new Error("IndexedDB is not available.");
    }
    this.databaseName = options.databaseName ?? PWA_CACHE_DATABASE_NAME;
    this.factory = factory;
    this.migrationHook = options.migrationHook;
    this.now = options.now ?? Date.now;
  }

  mode(): "indexeddb" {
    return "indexeddb";
  }

  durabilityMode(): "indexeddb" | "memory" {
    return "indexeddb";
  }

  durabilityKey(): string {
    return `indexeddb:${this.databaseName}`;
  }

  async initialize(): Promise<void> {
    if (this.initialized) {
      return;
    }
    await this.database();
    await this.resumePendingCleanups();
    this.initialized = true;
  }

  async get<T>(key: string): Promise<StoredCacheEntry<T> | null> {
    const database = await this.database();
    const transaction = database.transaction([ENTRY_STORE, PAYLOAD_STORE], "readonly");
    const metadataRequest = transaction.objectStore(ENTRY_STORE).get(key);
    const payloadRequest = transaction.objectStore(PAYLOAD_STORE).get(key);
    const [metadata, payload] = await Promise.all([
      requestValue<CacheEntryMetadata | undefined>(metadataRequest),
      requestValue<PayloadRecord | undefined>(payloadRequest),
      transactionDone(transaction),
    ]);
    return metadata && payload ? { metadata, payload: payload.payload as T } : null;
  }

  async put<T>(entry: StoredCacheEntry<T>): Promise<void> {
    const database = await this.database();
    const transaction = database.transaction([ENTRY_STORE, PAYLOAD_STORE], "readwrite");
    transaction.objectStore(ENTRY_STORE).put(entry.metadata);
    transaction.objectStore(PAYLOAD_STORE).put({ key: entry.metadata.key, payload: entry.payload } satisfies PayloadRecord);
    await transactionDone(transaction);
  }

  async touch(
    key: string,
    patch: Partial<Pick<CacheEntryMetadata,
      "accessLeaseExpiresAt" | "cachedAt" | "etag" | "expiresAt" | "lastAccessedAt" | "revision" | "staleAt"
    >>,
  ): Promise<boolean> {
    const database = await this.database();
    const transaction = database.transaction(ENTRY_STORE, "readwrite");
    const store = transaction.objectStore(ENTRY_STORE);
    const current = await requestValue<CacheEntryMetadata | undefined>(store.get(key));
    if (current) {
      store.put({ ...current, ...patch });
    }
    await transactionDone(transaction);
    return Boolean(current);
  }

  async delete(key: string): Promise<boolean> {
    const database = await this.database();
    const transaction = database.transaction([ENTRY_STORE, PAYLOAD_STORE], "readwrite");
    const existed = await requestValue<CacheEntryMetadata | undefined>(transaction.objectStore(ENTRY_STORE).get(key));
    transaction.objectStore(ENTRY_STORE).delete(key);
    transaction.objectStore(PAYLOAD_STORE).delete(key);
    await transactionDone(transaction);
    return Boolean(existed);
  }

  async list(filter: CacheFilter = {}): Promise<CacheEntryMetadata[]> {
    const database = await this.database();
    const transaction = database.transaction(ENTRY_STORE, "readonly");
    const entries = await requestValue<CacheEntryMetadata[]>(transaction.objectStore(ENTRY_STORE).getAll());
    await transactionDone(transaction);
    return entries.filter((metadata) => matchesFilter(metadata, filter));
  }

  async clear(filter: CacheFilter = {}, options: { durable?: boolean } = {}): Promise<number> {
    const marker = options.durable ? await this.writeCleanupMarker(filter) : null;
    try {
      const removed = await this.clearEntries(filter);
      if (marker) {
        await this.deleteCleanupMarker(marker.id);
      }
      return removed;
    } catch (error) {
      // A durable marker intentionally remains for the next successful bootstrap.
      throw error;
    }
  }

  async pendingCleanupCount(): Promise<number> {
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readonly");
    const records = await requestValue<unknown[]>(transaction.objectStore(METADATA_STORE).getAll());
    await transactionDone(transaction);
    return records.filter(isCleanupMarker).length;
  }

  private database(): Promise<IDBDatabase> {
    if (!this.databasePromise) {
      this.databasePromise = this.openDatabase();
    }
    return this.databasePromise;
  }

  private openDatabase(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = this.factory.open(this.databaseName, PWA_CACHE_DATABASE_VERSION);
      let migrationError: unknown;
      request.onupgradeneeded = (event) => {
        const database = request.result;
        const transaction = request.transaction;
        if (!transaction) {
          migrationError = new Error("IndexedDB migration transaction is unavailable.");
          return;
        }
        try {
          this.upgrade(database, transaction, event.oldVersion);
        } catch (error) {
          migrationError = error;
          transaction.abort();
        }
      };
      request.onerror = () => reject(migrationError ?? request.error ?? new Error("Unable to open PWA cache database."));
      request.onblocked = () => reject(new Error("PWA cache database upgrade is blocked by another client."));
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        resolve(database);
      };
    });
  }

  private upgrade(database: IDBDatabase, transaction: IDBTransaction, oldVersion: number): void {
    if (oldVersion < 1) {
      this.migrationHook?.("create-v1");
      database.createObjectStore(ENTRY_STORE, { keyPath: "key" });
    }
    const entries = transaction.objectStore(ENTRY_STORE);
    if (oldVersion < 2) {
      this.migrationHook?.("split-payloads-v2");
      const payloads = database.objectStoreNames.contains(PAYLOAD_STORE)
        ? transaction.objectStore(PAYLOAD_STORE)
        : database.createObjectStore(PAYLOAD_STORE, { keyPath: "key" });
      if (!database.objectStoreNames.contains(METADATA_STORE)) {
        database.createObjectStore(METADATA_STORE, { keyPath: "id" });
      }
      const cursorRequest = entries.openCursor();
      cursorRequest.onsuccess = () => {
        const cursor = cursorRequest.result;
        if (!cursor) {
          return;
        }
        const legacy = cursor.value as CacheEntryMetadata & { payload?: unknown };
        if (Object.prototype.hasOwnProperty.call(legacy, "payload")) {
          payloads.put({ key: legacy.key, payload: legacy.payload } satisfies PayloadRecord);
          const metadata = { ...legacy } as CacheEntryMetadata & { payload?: unknown };
          delete metadata.payload;
          cursor.update(metadata);
        }
        cursor.continue();
      };
      this.migrationHook?.("create-indices-v2");
      createIndex(entries, "principal", ["userId", "workspaceId"]);
      createIndex(entries, "app", ["userId", "workspaceId", "appId"]);
      createIndex(entries, "scope", ["userId", "workspaceId", "appId", "resource"]);
      createIndex(entries, "expiresAt", "expiresAt");
      createIndex(entries, "lastAccessedAt", "lastAccessedAt");
    }
    if (oldVersion < 3) {
      this.migrationHook?.("resource-schema-v3");
      const payloads = transaction.objectStore(PAYLOAD_STORE);
      const cursorRequest = entries.openCursor();
      cursorRequest.onsuccess = () => {
        const cursor = cursorRequest.result;
        if (!cursor) {
          return;
        }
        const metadata = cursor.value as Partial<CacheEntryMetadata>;
        if (metadata.schemaVersion !== PWA_CACHE_ENTRY_SCHEMA_VERSION
            || typeof metadata.schemaRevision !== "string"
            || !metadata.schemaRevision.trim()) {
          if (typeof metadata.key === "string") {
            payloads.delete(metadata.key);
          }
          cursor.delete();
        }
        cursor.continue();
      };
    }
  }

  private async writeCleanupMarker(filter: CacheFilter): Promise<CleanupMarker> {
    const marker: CleanupMarker = {
      createdAt: this.now(),
      filter,
      id: randomId(),
      kind: "cleanup",
    };
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readwrite");
    transaction.objectStore(METADATA_STORE).put(marker);
    await transactionDone(transaction);
    return marker;
  }

  private async deleteCleanupMarker(id: string): Promise<void> {
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readwrite");
    transaction.objectStore(METADATA_STORE).delete(id);
    await transactionDone(transaction);
  }

  private async clearEntries(filter: CacheFilter): Promise<number> {
    const database = await this.database();
    const transaction = database.transaction([ENTRY_STORE, PAYLOAD_STORE], "readwrite");
    const entries = transaction.objectStore(ENTRY_STORE);
    const payloads = transaction.objectStore(PAYLOAD_STORE);
    let removed = 0;
    const cursorRequest = entries.openCursor();
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result;
      if (!cursor) {
        return;
      }
      const metadata = cursor.value as CacheEntryMetadata;
      if (matchesFilter(metadata, filter)) {
        payloads.delete(metadata.key);
        cursor.delete();
        removed += 1;
      }
      cursor.continue();
    };
    await transactionDone(transaction);
    return removed;
  }

  private async resumePendingCleanups(): Promise<void> {
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readonly");
    const records = await requestValue<unknown[]>(transaction.objectStore(METADATA_STORE).getAll());
    await transactionDone(transaction);
    for (const marker of records.filter(isCleanupMarker)) {
      await this.clearEntries(marker.filter);
      await this.deleteCleanupMarker(marker.id);
    }
  }
}

function createIndex(store: IDBObjectStore, name: string, keyPath: string | string[]): void {
  if (!store.indexNames.contains(name)) {
    store.createIndex(name, keyPath, { unique: false });
  }
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB request failed."));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(transaction.error ?? new Error("IndexedDB transaction aborted."));
    transaction.onerror = () => reject(transaction.error ?? new Error("IndexedDB transaction failed."));
  });
}

function isCleanupMarker(value: unknown): value is CleanupMarker {
  if (!value || typeof value !== "object") {
    return false;
  }
  const marker = value as Partial<CleanupMarker>;
  return marker.kind === "cleanup" && typeof marker.id === "string" && Boolean(marker.filter);
}

function randomId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `cleanup-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
