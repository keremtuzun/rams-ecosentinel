import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("actual hosted results open in one click and never submit fake inference", async ({
  page,
  request,
}) => {
  const health = await (await request.get("/health")).json();
  test.skip(health.mode !== "evidence", "Requires authentic packaged evidence");
  const catalog = await (await request.get("/evidence/catalog.json")).json();
  expect(catalog.jobs.length).toBeGreaterThan(0);
  const completed = catalog.jobs[0];
  expect(
    (await (await request.get(`/api/jobs/${completed.id}`)).json()).report,
  ).toEqual(completed.report);
  expect(
    (await request.post("/api/jobs", { data: completed.request })).status(),
  ).toBe(503);
  await page.addInitScript(() =>
    localStorage.setItem("ecosentinel-guide-tr-v1", "done"),
  );
  const posted: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") posted.push(r.url());
  });
  await page.goto("/");
  await expect(page.locator(".header-meta")).toContainText("Hazır sonuçlar");
  await page.getByRole("button", { name: "İzmir · Sonucu aç" }).click();
  await expect(
    page.getByRole("heading", { name: "İzmir · Orman değişimi" }),
  ).toBeVisible();
  expect(posted).toEqual([]);
  await page.locator(".new-analysis summary").click();
  await expect(
    page.getByText("Yeni analiz sunucusu bağlı değil.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Analizi başlat" }),
  ).toHaveCount(0);
  await page.getByText("Ayrıntılar ve dosyalar", { exact: true }).click();
  const downloadPending = page.waitForEvent("download");
  await page.getByRole("link", { name: "Tablo (CSV)", exact: true }).click();
  const download = await downloadPending;
  expect(await download.failure()).toBeNull();
  const expected = await (
    await request.get(
      "/api/jobs/23e8032f-93b4-47cb-86a9-9882369d11d8/export/csv",
    )
  ).body();
  expect(await readFile((await download.path())!)).toEqual(expected);
  await page.getByRole("button", { name: "Marmaris · Sonucu aç" }).click();
  await expect(
    page.getByRole("heading", { name: "Marmaris · Orman değişimi" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Manavgat · Sonucu aç" }).click();
  await expect(
    page.getByRole("heading", { name: "Manavgat · Orman değişimi" }),
  ).toBeVisible();
  expect(posted).toEqual([]);
});
