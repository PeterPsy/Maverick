import type { FileCacheOpenResult } from "./fileCacheTypes";

const issued = new WeakMap<object, (signal: AbortSignal) => Promise<FileCacheOpenResult>>();
const BRAND: unique symbol = Symbol("maverick.file-read-retry");
export type FileReadRetryExecutor = Readonly<{ [BRAND]: true; identity: string }>;

/** Internal issuance: only PwaFileCache supplies the SDK-owned read implementation. */
export function issueFileReadRetryExecutor(
  identity: string,
  read: (signal: AbortSignal) => Promise<FileCacheOpenResult>,
): FileReadRetryExecutor {
  const executor = Object.freeze({ [BRAND]: true as const, identity });
  issued.set(executor, read);
  return executor;
}

export function validateFileReadRetryExecutor(executor: FileReadRetryExecutor): void {
  if (!issued.has(executor)) throw new TypeError("File retries require a host-issued PwaFileCache read executor.");
}

export function executeFileReadRetryExecutor(executor: FileReadRetryExecutor, signal: AbortSignal): Promise<FileCacheOpenResult> {
  validateFileReadRetryExecutor(executor);
  return issued.get(executor)!(signal);
}
