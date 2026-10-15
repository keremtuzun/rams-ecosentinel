import { expect, test } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  // Only the shell is mocked: guide behavior is independent of scientific results.
  await page.route("**/health", (r) =>
    r.fulfill({ json: { analysis_available: false } }),
  );
  await page.route("**/api/regions", (r) =>
    r.fulfill({
      json: [
        {
          id: "milas",
          bbox: [27.84, 37.08, 27.97, 37.2],
          before: ["2020-06-01", "2020-06-30"],
          after: ["2022-06-01", "2022-06-30"],
        },
      ],
    }),
  );
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [] }));
});
test("first visit guide completes, stays dismissed, and can be restarted", async ({
  page,
}) => {
  await page.goto("/");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Bir bölge seç");
  await page.getByRole("button", { name: "İleri" }).click();
  await expect(dialog).toContainText("Değişimi haritada gör");
  await page.getByRole("button", { name: "İleri" }).click();
  await expect(dialog).toContainText("Önce ve sonrayı karşılaştır");
  await page.getByRole("button", { name: "Geri", exact: true }).click();
  await expect(dialog).toContainText("Değişimi haritada gör");
  await page.getByRole("button", { name: "İleri" }).click();
  await page.getByRole("button", { name: "İleri" }).click();
  await page.getByRole("button", { name: "Başlayalım" }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Rehber" })).toBeVisible();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "Rehber" }).click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Rehber" })).toBeFocused();
});
test("mobile guide traps keyboard focus and fits the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "İleri" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Rehberi kapat" }),
  ).toBeFocused();
  const box = await page.getByRole("dialog").boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  await page.getByRole("button", { name: "Atla", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
