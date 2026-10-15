import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import { decodeEvidence } from "../scripts/build-assets.mjs";

const hash = (data: Buffer) => createHash("sha256").update(data).digest("hex");
function fixture(extra?: { path: string; data: string }) {
  // Build bootstrap fixture only; never served or used as satellite evidence.
  const catalog = Buffer.from(
    JSON.stringify({ jobs: [{ status: "succeeded", id: "unit-only" }] }),
  );
  const checksums = Buffer.from(
    JSON.stringify({ "catalog.json": hash(catalog) }),
  );
  const files = [
    { path: "catalog.json", data: catalog.toString("base64") },
    { path: "checksums.json", data: checksums.toString("base64") },
  ];
  if (extra) files.push(extra);
  return gzipSync(
    JSON.stringify({ format: "ecosentinel-build-assets-v1", files }),
  );
}

test("pinned build artifacts reject tampering, unsafe paths and incomplete manifests", () => {
  const good = fixture();
  expect(decodeEvidence(good, hash(good)).size).toBe(2);
  expect(() => decodeEvidence(good, "0".repeat(64))).toThrow(
    "checksum mismatch",
  );
  const traversal = fixture({ path: "../.env", data: "eA==" });
  expect(() => decodeEvidence(traversal, hash(traversal))).toThrow(
    "Invalid build asset path",
  );
  const extra = fixture({
    path: "jobs/00000000-0000-0000-0000-000000000000/report.json",
    data: "e30=",
  });
  expect(() => decodeEvidence(extra, hash(extra))).toThrow(
    "file count mismatch",
  );
});
