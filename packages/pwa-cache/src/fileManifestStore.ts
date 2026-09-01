import type {
  FileCacheCleanupMarker,
  FileCacheFilter,
  FileCacheManifestStore,
  FileCachePublishResult,
  FileCacheRecord,
} from "./fileCacheTypes";

export const PWA_FILE_CACHE_DATABASE_NAME = "maverick-pwa-file-v1";
export const PWA_FILE_CACHE_DATABASE_VERSION = 1;
const RECORD_STORE = "files";
const METADATA_STORE = "metadata";
const STATE_ID = "file-cache-state";

type FileCacheStateMetadata = {
  cleanupEpoch: number;
  id: typeof STATE_ID;
  kind: "file-cache-state";
  nextWriteGeneration: number;
};

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

  async getCleanupEpoch(): Promise<number> {
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readonly");
    const state = await requestValue<unknown>(transaction.objectStore(METADATA_STORE).get(STATE_ID));
    await transactionDone(transaction);
    return fileCacheState(state).cleanupEpoch;
  }

  async reserveWriting(record: FileCacheRecord, expectedCleanupEpoch: number): Promise<FileCacheRecord | null> {
    const database = await this.database();
    const transaction = database.transaction([RECORD_STORE, METADATA_STORE], "readwrite");
    const records = transaction.objectStore(RECORD_STORE);
    const metadata = transaction.objectStore(METADATA_STORE);
    const [stateValue, metadataValues, current, allRecords] = await Promise.all([
      requestValue<unknown>(metadata.get(STATE_ID)),
      requestValue<unknown[]>(metadata.getAll()),
      requestValue<FileCacheRecord | undefined>(records.get(record.key)),
      requestValue<FileCacheRecord[]>(records.getAll()),
    ]);
    const state = fileCacheState(stateValue);
    if (state.cleanupEpoch !== expectedCleanupEpoch
        || metadataValues.some((value) => isCleanupMarker(value) && fileCacheFilterMatches(record, value.filter))
        || (current && !sameWritingReservation(current, record))) {
      await transactionDone(transaction);
      return null;
    }
    if (current) {
      await transactionDone(transaction);
      return structuredClone(current);
    }
    const reserved: FileCacheRecord = {
      ...structuredClone(record),
      cleanupEpoch: state.cleanupEpoch,
      writeGeneration: allRecords.reduce(
        (highest, candidate) => Math.max(highest, safeWriteGeneration(candidate)),
        state.nextWriteGeneration,
      ) + 1,
    };
    records.put(reserved);
    metadata.put({ ...state, nextWriteGeneration: reserved.writeGeneration });
    await transactionDone(transaction);
    return reserved;
  }

  async updateWriting(record: FileCacheRecord): Promise<boolean> {
    return this.updateRecord(record, "writing");
  }

  async updateReady(record: FileCacheRecord): Promise<boolean> {
    return this.updateRecord(record, "ready");
  }

  async deleteWriting(record: FileCacheRecord): Promise<boolean> {
    const database = await this.database();
    const transaction = database.transaction(RECORD_STORE, "readwrite");
    const store = transaction.objectStore(RECORD_STORE);
    const current = await requestValue<FileCacheRecord | undefined>(store.get(record.key));
    if (current?.state === "writing" && sameRecordGeneration(current, record)) {
      store.delete(record.key);
      await transactionDone(transaction);
      return true;
    }
    await transactionDone(transaction);
    return false;
  }

  async publishReady(record: FileCacheRecord): Promise<FileCachePublishResult> {
    const database = await this.database();
    const transaction = database.transaction([RECORD_STORE, METADATA_STORE], "readwrite");
    const recordsStore = transaction.objectStore(RECORD_STORE);
    const metadataStore = transaction.objectStore(METADATA_STORE);
    const [stateValue, metadataValues, current, allRecords] = await Promise.all([
      requestValue<unknown>(metadataStore.get(STATE_ID)),
      requestValue<unknown[]>(metadataStore.getAll()),
      requestValue<FileCacheRecord | undefined>(recordsStore.get(record.key)),
      requestValue<FileCacheRecord[]>(recordsStore.getAll()),
    ]);
    const state = fileCacheState(stateValue);
    const sameIdentityRecords = allRecords.filter((candidate) => sameFileIdentity(candidate, record));
    const superseded = sameIdentityRecords.some((candidate) => candidate.writeGeneration > record.writeGeneration);
    if (state.cleanupEpoch !== record.cleanupEpoch
        || metadataValues.some((value) => isCleanupMarker(value) && fileCacheFilterMatches(record, value.filter))
        || current?.state !== "writing"
        || !sameRecordGeneration(current, record)
        || superseded) {
      await transactionDone(transaction);
      return { obsoleteRecords: [], published: false };
    }
    const obsoleteRecords = sameIdentityRecords.filter((candidate) => candidate.key !== record.key);
    recordsStore.put(structuredClone(record));
    obsoleteRecords.forEach((candidate) => recordsStore.delete(candidate.key));
    await transactionDone(transaction);
    return { obsoleteRecords: structuredClone(obsoleteRecords), published: true };
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
    const database = await this.database();
    const transaction = database.transaction(METADATA_STORE, "readwrite");
    const store = transaction.objectStore(METADATA_STORE);
    const state = fileCacheState(await requestValue<unknown>(store.get(STATE_ID)));
    const marker: FileCacheCleanupMarker = {
      cleanupEpoch: state.cleanupEpoch + 1,
      createdAt: this.now(),
      filter: structuredClone(filter),
      id: globalThis.crypto?.randomUUID?.() ?? `file-cleanup-${this.now()}-${Math.random().toString(16).slice(2)}`,
      kind: "file-cache-cleanup",
    };
    store.put({ ...state, cleanupEpoch: marker.cleanupEpoch });
    store.put(marker);
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

  private async updateRecord(record: FileCacheRecord, expectedState: "ready" | "writing"): Promise<boolean> {
    const database = await this.database();
    const transaction = database.transaction([RECORD_STORE, METADATA_STORE], "readwrite");
    const records = transaction.objectStore(RECORD_STORE);
    const metadata = transaction.objectStore(METADATA_STORE);
    const [stateValue, metadataValues, current] = await Promise.all([
      requestValue<unknown>(metadata.get(STATE_ID)),
      requestValue<unknown[]>(metadata.getAll()),
      requestValue<FileCacheRecord | undefined>(records.get(record.key)),
    ]);
    const state = fileCacheState(stateValue);
    if ((expectedState === "writing" && state.cleanupEpoch !== record.cleanupEpoch)
        || metadataValues.some((value) => isCleanupMarker(value) && fileCacheFilterMatches(record, value.filter))
        || current?.state !== expectedState
        || !sameRecordGeneration(current, record)) {
      await transactionDone(transaction);
      return false;
    }
    records.put(structuredClone(record));
    await transactionDone(transaction);
    return true;
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
    && Number.isSafeInteger(marker.cleanupEpoch)
    && Number(marker.cleanupEpoch) >= 1
    && Boolean(marker.filter)
    && typeof marker.filter === "object";
}

function fileCacheState(value: unknown): FileCacheStateMetadata {
  if (value && typeof value === "object") {
    const state = value as Partial<FileCacheStateMetadata>;
    if (state.id === STATE_ID
        && state.kind === "file-cache-state"
        && Number.isSafeInteger(state.cleanupEpoch)
        && Number(state.cleanupEpoch) >= 0
        && Number.isSafeInteger(state.nextWriteGeneration)
        && Number(state.nextWriteGeneration) >= 0) {
      return state as FileCacheStateMetadata;
    }
  }
  return {
    cleanupEpoch: 0,
    id: STATE_ID,
    kind: "file-cache-state",
    nextWriteGeneration: 0,
  };
}

function sameWritingReservation(left: FileCacheRecord, right: FileCacheRecord): boolean {
  return left.state === "writing"
    && right.state === "writing"
    && left.writerSessionId === right.writerSessionId
    && left.opfsPath === right.opfsPath;
}

function sameRecordGeneration(left: FileCacheRecord, right: FileCacheRecord): boolean {
  return left.key === right.key
    && left.cleanupEpoch === right.cleanupEpoch
    && left.writeGeneration === right.writeGeneration
    && left.writerSessionId === right.writerSessionId
    && left.opfsPath === right.opfsPath;
}

function sameFileIdentity(left: FileCacheRecord, right: FileCacheRecord): boolean {
  return left.userId === right.userId
    && left.workspaceId === right.workspaceId
    && left.appId === right.appId
    && left.fileId === right.fileId;
}

function safeWriteGeneration(record: FileCacheRecord): number {
  return Number.isSafeInteger(record.writeGeneration) && record.writeGeneration >= 0 ? record.writeGeneration : 0;
}
