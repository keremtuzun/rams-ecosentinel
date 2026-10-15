import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
const target = resolve("public/vendor/maplibre");
await mkdir(target, { recursive: true });
for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  await copyFile(
    resolve("node_modules/maplibre-gl/dist", name),
    resolve(target, name),
  );
}
