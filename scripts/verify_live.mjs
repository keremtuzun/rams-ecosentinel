// Opt-in black-box live verification. Creates at most one REAL analysis when
// --submit-real-analysis is explicitly supplied. Credentials stay in ignored artifacts.
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const require = createRequire(
  new URL("../apps/web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const origin =
  process.argv.find((x) => x.startsWith("https://")) ||
  "https://rams-ecosentinel.vercel.app";
const submit = process.argv.includes("--submit-real-analysis");
const resume = process.argv.includes("--resume");
const out = new URL("../artifacts/deployment/debug/", import.meta.url);
await mkdir(out, { recursive: true });
const evidence = {
  origin,
  verified_at: new Date().toISOString(),
  checks: {},
  stages: [],
  downloads: [],
  browser_errors: [],
};
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: "tr-TR",
  timezoneId: "Europe/Istanbul",
  ...(resume
    ? {
        storageState: new URL("session.json", out).pathname.replace(
          /^\/(\w:)/,
          "$1",
        ),
      }
    : {}),
});
const page = await context.newPage();
page.on("pageerror", (e) => evidence.browser_errors.push(e.message));
let job;
try {
  await page.goto(origin);
  await expect(page.locator(".header-meta")).toContainText("Analiz açık", {
    timeout: 60000,
  });
  if (await page.getByRole("dialog").isVisible()) {
    await page.getByRole("button", { name: "Atla", exact: true }).click();
    evidence.checks.guide = "PASS";
  }
  assert(
    await page
      .locator(".brand-logo")
      .evaluate((img) => img.complete && img.naturalWidth > 0),
  );
  evidence.checks.logo = "PASS";
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `overflow at ${width}`,
    );
  }
  evidence.checks.viewport_widths = [320, 390, 768, 1440];
  await page.screenshot({
    path: new URL("desktop.png", out).pathname.replace(/^\/(\w:)/, "$1"),
    fullPage: true,
  });
  if (submit && !resume) {
    await page.getByLabel("Bölge ara").fill("Ankara");
    await page
      .getByRole("button", { name: "Haritada ara", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Ankara Ankara", exact: true })
      .click();
    await page.waitForTimeout(700); // The application's 500 ms camera transition.
    for (let i = 0; i < 2; i++)
      await page
        .getByRole("button", { name: "Uzaklaştır", exact: true })
        .click();
    await page.waitForTimeout(700);
    await page.getByRole("button", { name: "Serbest çiz" }).click();
    const canvas = page.locator(".maplibregl-canvas");
    await expect(canvas).toHaveCSS("cursor", "crosshair");
    const b = await canvas.boundingBox();
    // A concave L, drawn through the genuine UI. Padding must not count as missing data.
    for (const [x, y] of [
      [0.3, 0.2],
      [0.7, 0.2],
      [0.7, 0.38],
      [0.43, 0.38],
      [0.43, 0.75],
      [0.3, 0.75],
    ])
      await canvas.click({ position: { x: b.width * x, y: b.height * y } });
    await page
      .getByRole("button", { name: "Alanı bitir", exact: true })
      .click();
    await expect(page.locator(".draw-hint")).toHaveCount(0);
    await page.getByLabel("Önceki tarih", { exact: true }).fill("2022-06-30");
    await page.getByLabel("Sonraki tarih", { exact: true }).fill("2024-06-30");
    const pending = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/jobs" &&
        r.request().method() === "POST",
      { timeout: 65000 },
    );
    await page.getByRole("button", { name: "Analizi başlat" }).click();
    const response = await pending;
    assert.equal(response.status(), 202, await response.text());
    job = await response.json();
    await context.storageState({
      path: new URL("session.json", out).pathname.replace(/^\/(\w:)/, "$1"),
    });
    await writeFile(new URL("job-id.txt", out), job.id);
    evidence.checks.place_search_and_concave_drawing = "PASS";
    await page.reload();
    await expect(page.locator(".execution-state")).toBeVisible({
      timeout: 60000,
    });
    evidence.checks.reload_running_job = "PASS";
    await context.setOffline(true);
    await expect(page.locator(".error[role=alert]")).toContainText("Bağlantı", {
      timeout: 15000,
    });
    await context.setOffline(false);
    evidence.checks.browser_network_interruption = "PASS";
  } else if (resume) {
    const id = (await readFile(new URL("job-id.txt", out), "utf8")).trim();
    job = await (await context.request.get(`${origin}/api/jobs/${id}`)).json();
  }
  if (job) {
    evidence.job_id = job.id;
    const deadline = Date.now() + 720000;
    let previous;
    while (Date.now() < deadline) {
      const response = await context.request.get(
        `${origin}/api/jobs/${job.id}`,
        { timeout: 65000 },
      );
      assert.equal(response.status(), 200);
      job = await response.json();
      const state = `${job.status}:${job.stage}`;
      if (state !== previous) {
        evidence.stages.push({ state, at: new Date().toISOString() });
        console.log(state);
        previous = state;
      }
      if (["succeeded", "failed"].includes(job.status)) break;
      await page.waitForTimeout(3000);
    }
    assert.equal(
      job.status,
      "succeeded",
      job.error || "job did not finish within 12 minutes",
    );
    evidence.report = {
      grid: job.report.grid,
      clear_fraction: job.report.clear_fraction,
      sources: job.report.source_observations.map((s) => ({
        scene_id: s.scene_id,
        acquired_at: s.acquired_at,
        clear_fraction: s.clear_fraction,
      })),
      checkpoint_sha256: job.report.model_checkpoint_sha256,
      runtime: job.report.inference_runtime,
    };
    assert.equal(evidence.report.runtime, "onnx");
    await expect(
      page.getByRole("link", { name: "Raporu indir (PDF)" }),
    ).toBeVisible({ timeout: 15000 });
    const downloadPending = page.waitForEvent("download", { timeout: 90000 });
    await page.getByRole("link", { name: "Raporu indir (PDF)" }).click();
    const download = await downloadPending;
    assert.equal(await download.failure(), null);
    await download.saveAs(
      new URL("assessment-browser.pdf", out).pathname.replace(/^\/(\w:)/, "$1"),
    );
    for (const [path, filename] of [
      ["export/pdf", "assessment.pdf"],
      ["export/csv", "assessment.csv"],
      ["export/json", "report.json"],
      ["export/geojson", "change.geojson"],
      ["files/score.tif", "score.tif"],
      ["files/indices.tif", "indices.tif"],
    ]) {
      const initial = await context.request.get(
        `${origin}/api/jobs/${job.id}/${path}`,
        { maxRedirects: 0, timeout: 90000 },
      );
      const signed = initial.status() === 307;
      const response = signed
        ? await context.request.get(initial.headers().location, {
            timeout: 120000,
          })
        : initial;
      assert.equal(response.status(), 200);
      const body = await response.body();
      const digest = createHash("sha256").update(body).digest("hex");
      if (job.report.checksums[filename])
        assert.equal(digest, job.report.checksums[filename]);
      if (filename === "assessment.pdf") {
        assert(body.subarray(0, 5).equals(Buffer.from("%PDF-")));
        assert(body.subarray(-50).toString().includes("%%EOF"));
        assert.equal(
          digest,
          createHash("sha256")
            .update(await readFile(new URL("assessment-browser.pdf", out)))
            .digest("hex"),
        );
      }
      if (filename === "report.json")
        assert.deepEqual(JSON.parse(body), job.report);
      await writeFile(new URL(filename, out), body);
      evidence.downloads.push({
        filename,
        bytes: body.length,
        sha256: digest,
        signed_redirect: signed,
      });
    }
    assert(
      evidence.downloads.some((d) => d.signed_redirect && d.bytes > 4000000),
      "large signed download not exercised",
    );
    const ring = job.request.geometry.coordinates[0];
    const [lon, lat] = ring[0];
    const inspection = await context.request.get(
      `${origin}/api/jobs/${job.id}/inspect?longitude=${lon}&latitude=${lat}`,
    );
    assert.equal(inspection.status(), 200);
    evidence.checks.pixel_inspection = await inspection.json();
    const stranger = await browser.newContext();
    assert.equal((await stranger.request.get(`${origin}/health`)).status(), 200);
    const strangerJobs = await (await stranger.request.get(`${origin}/api/jobs`)).json();
    assert(!strangerJobs.some(record => record.id === job.id));
    evidence.checks.session_isolation = [];
    for (const suffix of [
      "",
      "/export/pdf",
      "/export/json",
      "/files/score.tif",
      `/inspect?longitude=${lon}&latitude=${lat}`,
    ]) {
      const response = await stranger.request.get(
        `${origin}/api/jobs/${job.id}${suffix}`,
      );
      assert.equal(response.status(), 404);
      evidence.checks.session_isolation.push({
        route: suffix || "/job",
        status: response.status(),
      });
    }
    await stranger.close();
    await page.reload();
    await expect(
      page.getByRole("link", { name: "Raporu indir (PDF)" }),
    ).toBeVisible({ timeout: 60000 });
    evidence.checks.reload_completed_job = "PASS";
    await page.screenshot({
      path: new URL("completed-desktop.png", out).pathname.replace(
        /^\/(\w:)/,
        "$1",
      ),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await page.screenshot({
      path: new URL("completed-mobile.png", out).pathname.replace(
        /^\/(\w:)/,
        "$1",
      ),
      fullPage: true,
    });
  }
  assert.deepEqual(evidence.browser_errors, []);
  evidence.status = "PASS";
} catch (error) {
  evidence.status = "FAIL";
  evidence.failure = error.message;
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await context.setOffline(false).catch(() => {});
  await writeFile(
    new URL(
      submit || resume
        ? "live-verification.json"
        : "read-only-verification.json",
      out,
    ),
    JSON.stringify(evidence, null, 2),
  );
  console.log(
    JSON.stringify({
      status: evidence.status,
      job_id: evidence.job_id,
      checks: Object.keys(evidence.checks),
      downloads: evidence.downloads.map((d) => ({
        filename: d.filename,
        bytes: d.bytes,
        signed: d.signed_redirect,
      })),
    }),
  );
  await browser.close();
}
