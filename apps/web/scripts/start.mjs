import { cp, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
const bundle = resolve(".next/standalone");
await mkdir(resolve(bundle, ".next"), { recursive: true });
await cp(resolve(".next/static"), resolve(bundle, ".next/static"), {
  recursive: true,
});
await cp(resolve("public"), resolve(bundle, "public"), { recursive: true });
const child = spawn(process.execPath, [resolve(bundle, "server.js")], {
  stdio: "inherit",
  env: {
    ...process.env,
    HOSTNAME: "127.0.0.1",
    PORT: process.env.PORT || "3000",
  },
});
child.on("exit", (code) => process.exit(code || 0));
process.on("SIGINT", () => child.kill("SIGINT"));
process.on("SIGTERM", () => child.kill("SIGTERM"));
