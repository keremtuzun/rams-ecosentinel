// An opt-in browser against the loopback Docker frontend. No mocked routes or data.
import { createRequire } from "node:module";
import { readFile, writeFile } from "node:fs/promises";
const require = createRequire(
  new URL("../apps/web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const [phase, filename] = process.argv.slice(2);
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  await context.addInitScript(() =>
    localStorage.setItem("ecosentinel-guide-tr-v1", "done"),
  );
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3000/");
  if (phase === "submit") {
    const request = {
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [32.73236805535424, 39.97672066337469],
            [32.97561018452612, 39.97672066337469],
            [32.97561018452612, 39.942704290858444],
            [32.81157623136579, 39.942704290858444],
            [32.81157623136579, 39.87246514374033],
            [32.73236805535424, 39.87246514374033],
            [32.73236805535424, 39.97672066337469],
          ],
        ],
      },
      before_start: "2022-06-01",
      before_end: "2022-06-30",
      after_start: "2024-06-01",
      after_end: "2024-06-30",
      module: "habitat",
    };
    const result = await page.evaluate(async (data) => {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      return { status: response.status, job: await response.json() };
    }, request);
    expect(result.status, JSON.stringify(result.job)).toBe(202);
    await writeFile(filename, JSON.stringify(result.job));
    console.log(
      "Browser submitted exactly one job to the loopback Docker stack",
    );
  } else if (phase === "review") {
    const job = JSON.parse(await readFile(filename, "utf8"));
    await expect(
      page.getByRole("heading", { name: /Orman değişimi/ }),
    ).toBeVisible({ timeout: 60000 });
    await page.getByText("Ayrıntılar ve dosyalar", { exact: true }).click();
    for (const name of ["↓ Raporu indir (PDF)", "Tablo (CSV)"]) {
      const pending = page.waitForEvent("download");
      await page.getByRole("link", { name, exact: true }).click();
      const download = await pending;
      expect(await download.failure()).toBeNull();
    }
    await page.screenshot({ path: filename + ".desktop.png", fullPage: true });
    await page.reload();
    await expect(
      page.getByRole("heading", { name: /Orman değişimi/ }),
    ).toBeVisible({ timeout: 60000 });
    const current = await page.evaluate(
      async (id) => (await fetch(`/api/jobs/${id}`)).json(),
      job.id,
    );
    expect(current.status).toBe("succeeded");
    await page.setViewportSize({ width: 390, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: filename + ".mobile.png", fullPage: true });
    expect(errors).toEqual([]);
    console.log(
      "Real result, PDF/CSV browser downloads, refresh, mobile overflow and JS errors: PASS",
    );
  } else throw new Error("Expected submit or review");
} finally {
  await browser.close();
}
