import type {
  FileCacheCleanupMarker,
  FileCacheFilter,
  FileCacheManifestStore,
  FileCacheRecord,
} from "./fileCacheTypes";

export const PWA_FILE_CACHE_DATABASE_NAME = "maverick-pwa-file-v1";
export const PWA_FILE_CACHE_DATABASE_VERSION = 1;
const RECORD_STORE = "files";
const METADATA_STORE = "metadata";

export type IndexedDbFileCacheManifestStoreOptions = {
  databaseName?: string;
  factory?: IDBFactory;
  now?: () => number;
};

export class IndexedDbFileCacheManifestStore implements FileCacheManifestStore {
  private readonly databaseName: string;
  private readonly factory: IDBFactory;
  private readonly now: () => number;
  private databasePromise: Promise<IDBDatabase> | null = null;

  constructor(options: IndexedDbFileCacheManifestStoreOptions = {}) {
    const factory = options.factory ?? globalThis.indexedDB;
    if (!factory) throw new Error("IndexedDB is not available.");
    this.databaseName = options.databaseName ?? PWA_FILE_CACHE_DATABASE_NAME;
    this.factory = factory;
    this.now = options.now ?? Date.now;
  }

  async initialize(): Promise<void> {
    await this.database();
  }

  async get(key: string): Promise<FileCacheRecord | null> {
    const database = await this.database();
    const transaction = database.transaction(RECORD_STORE, "readonly");
    const value = await requestValue<FileCacheRecord | undefined>(transaction.objectStore(RECORD_STORE).get(key));
    await transactionDone(transaction);
    return value ?? null;
  }

  async put(record: FileCacheRecord): Promise<void> {
    const database = await this.database();
    const transaction = database.transaction(RECORD_STORE, "readwrite");
    transaction.objectStore(RECORD_STORE).put(structuredClone(record));
    await transactionDone(transaction);
  }

  async delete(key: string): Promise<boolean> {
    const database = await this.database();
    const transaction = database.transaction(RECORD_STORE, "readwrite");
    const store = transaction.objectStore(RECORD_STORE);
    const existing = await requestValue<FileCacheRecord | undefined>(store.get(key));
    store.delete(key);
    await transactionDone(transaction);
    return Boolean(existing);
  }

  async list(filter: FileCacheFilter = {}): Promise<FileCacheRecord[]> {
    const database = await this.database();
    const transaction = database.transaction(RECORD_STORE, "readonly");
    const records = await requestValue<FileCacheRecord[]>(transaction.objectStore(RECORD_STORE).getAll());
    await transactionDone(transaction);
    return records.filter((record) => fileCacheFilterMatches(record, filter));
  }

  async createCleanupMarker(filter: FileCacheFilter): Promise<FileCacheCleanupMarker> {
    const marker: FileCacheCleanupMarker = {
      createdAt: this.now(),
      filter: structuredClone(filter),
      id: globalThis.crypto?.randomUUID?.() ?? `file-cleanup-${this.now()}-${Math.random().toString(16).slice(2)}`,
      kind: "file-cache-cleanup",
    };
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readwrite");
    transaction.objectStore(METADATA_STORE).put(marker);
    await transactionDone(transaction);
    return marker;
  }

  async deleteCleanupMarker(id: string): Promise<void> {
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readwrite");
    transaction.objectStore(METADATA_STORE).delete(id);
    await transactionDone(transaction);
  }

  async listCleanupMarkers(): Promise<FileCacheCleanupMarker[]> {
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readonly");
    const records = await requestValue<unknown[]>(transaction.objectStore(METADATA_STORE).getAll());
    await transactionDone(transaction);
    return records.filter(isCleanupMarker);
  }

  private database(): Promise<IDBDatabase> {
    if (!this.databasePromise) this.databasePromise = this.openDatabase();
    return this.databasePromise;
  }

  private openDatabase(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = this.factory.open(this.databaseName, PWA_FILE_CACHE_DATABASE_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        if (!database.objectStoreNames.contains(RECORD_STORE)) {
          const records = database.createObjectStore(RECORD_STORE, { keyPath: "key" });
          records.createIndex("principal", ["userId", "workspaceId", "appId"], { unique: false });
          records.createIndex("file", ["userId", "workspaceId", "appId", "fileId"], { unique: false });
          records.createIndex("lastAccessedAt", "lastAccessedAt", { unique: false });
          records.createIndex("state", "state", { unique: false });
        }
        if (!database.objectStoreNames.contains(METADATA_STORE)) {
          database.createObjectStore(METADATA_STORE, { keyPath: "id" });
        }
      };
      request.onerror = () => reject(request.error ?? new Error("Unable to open PWA file-cache manifest."));
      request.onblocked = () => reject(new Error("PWA file-cache manifest upgrade is blocked by another client."));
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        resolve(database);
      };
    });
  }
}

export function fileCacheFilterMatches(record: FileCacheRecord, filter: FileCacheFilter = {}): boolean {
  for (const field of ["userId", "workspaceId", "appId", "fileId", "sourceVersion", "state"] as const) {
    if (filter[field] !== undefined && record[field] !== filter[field]) return false;
  }
  return true;
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

function isCleanupMarker(value: unknown): value is FileCacheCleanupMarker {
  if (!value || typeof value !== "object") return false;
  const marker = value as Partial<FileCacheCleanupMarker>;
  return marker.kind === "file-cache-cleanup"
    && typeof marker.id === "string"
    && Boolean(marker.filter)
    && typeof marker.filter === "object";
}
