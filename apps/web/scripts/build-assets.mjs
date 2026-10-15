import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { gunzipSync } from "node:zlib";

const digest = (data) => createHash("sha256").update(data).digest("hex");
const allowed =
  /^(catalog\.json|checksums\.json|jobs\/[0-9a-f-]{36}\/(before\.png|after\.png|overlay\.png|map\.png|assessment\.pdf|assessment\.csv|report\.json|change\.geojson|score\.tif|mask\.tif|indices\.tif|uncertainty\.tif))$/;

export function decodeEvidence(data, sha256) {
  if (!/^[a-f0-9]{64}$/.test(sha256) || digest(data) !== sha256)
    throw new Error("Build asset checksum mismatch");
  const bundle = JSON.parse(gunzipSync(data, { maxOutputLength: 120_000_000 }));
  if (
    bundle.format !== "ecosentinel-build-assets-v1" ||
    !Array.isArray(bundle.files) ||
    bundle.files.length > 1000
  )
    throw new Error("Invalid build asset bundle");
  const files = new Map();
  let total = 0;
  for (const entry of bundle.files) {
    if (
      !allowed.test(entry.path) ||
      files.has(entry.path) ||
      typeof entry.data !== "string"
    )
      throw new Error("Invalid build asset path");
    const content = Buffer.from(entry.data, "base64");
    total += content.length;
    if (total > 80_000_000) throw new Error("Build asset bundle too large");
    files.set(entry.path, content);
  }
  if (!files.has("catalog.json") || !files.has("checksums.json"))
    throw new Error("Missing evidence manifest");
  const checksums = JSON.parse(files.get("checksums.json"));
  if (Object.keys(checksums).length !== files.size - 1)
    throw new Error("Evidence manifest file count mismatch");
  for (const [path, content] of files)
    if (path !== "checksums.json" && checksums[path] !== digest(content))
      throw new Error("Evidence manifest checksum mismatch");
  const catalog = JSON.parse(files.get("catalog.json"));
  if (
    !catalog.jobs?.length ||
    catalog.jobs.some((job) => job.status !== "succeeded")
  )
    throw new Error("Only completed real evidence may be packaged");
  return files;
}

export async function restoreEvidence(files, destination) {
  for (const [path, content] of files) {
    const target = join(destination, path);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, content);
  }
}
