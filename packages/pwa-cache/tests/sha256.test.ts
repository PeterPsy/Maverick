import { describe, expect, it } from "vitest";
import { IncrementalSha256, sha256Blob } from "../src/testing";

describe("incremental SHA-256", () => {
  it("matches standard vectors across arbitrary chunk boundaries", async () => {
    const hash = new IncrementalSha256();
    hash.update(new TextEncoder().encode("a"));
    hash.update(new TextEncoder().encode("bc"));
    expect(hash.hexDigest()).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");

    await expect(sha256Blob(new Blob([]))).resolves.toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });

  it("hashes payloads spanning more than one compression block", () => {
    const hash = new IncrementalSha256();
    hash.update(new TextEncoder().encode("a".repeat(1_000)));
    expect(hash.hexDigest()).toBe("41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3");
  });
});
