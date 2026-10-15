import { resolve } from "node:path";
import { get } from "@vercel/blob";
import { decodeEvidence, restoreEvidence } from "./build-assets.mjs";

const path = process.env.ECOSENTINEL_BUILD_ASSET_PATH;
const hash = process.env.ECOSENTINEL_BUILD_ASSET_SHA256;
if (!path && !hash && !process.env.VERCEL) {
  console.log("Local build: using any locally installed evidence");
} else {
  if (!/^build-assets\/web\/[a-f0-9]{64}\.json\.gz$/.test(path || "") || !hash)
    throw new Error("Pinned private build assets are not configured");
  const result = await get(path, { access: "private", useCache: false });
  if (!result || result.statusCode !== 200 || result.blob.size > 80_000_000)
    throw new Error("Private build assets are unavailable");
  const data = Buffer.from(await new Response(result.stream).arrayBuffer());
  const files = decodeEvidence(data, hash);
  await restoreEvidence(files, resolve("public/evidence"));
  console.log(`Restored ${files.size} checksum-verified evidence files`);
}
