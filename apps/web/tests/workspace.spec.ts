import { expect, test } from "@playwright/test";
// UI-only fixtures; never packaged, used as scientific results, or shown in delivery screenshots.
const regions = [
  {
    id: "marmaris",
    name: "Marmaris",
    bbox: [28.22, 36.98, 28.35, 37.1],
    before: ["2020-06-01", "2020-06-30"],
    after: ["2022-06-01", "2022-06-30"],
  },
  {
    id: "izmir",
    name: "Izmir",
    bbox: [26.96, 38.13, 27.09, 38.25],
    before: ["2018-06-01", "2018-06-30"],
    after: ["2020-06-01", "2020-06-30"],
  },
];
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem("ecosentinel-guide-tr-v1", "done"),
  );
  await page.route(/\/(?:api\/.*|health)(?:\?.*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/health")
      return route.fulfill({
        json: { status: "ok", analysis_available: true },
      });
    if (path === "/api/regions") return route.fulfill({ json: regions });
    if (path === "/api/jobs" && route.request().method() === "GET")
      return route.fulfill({ json: [] });
    if (path === "/api/jobs")
      return route.fulfill({
        status: 202,
        json: {
          id: "contract-test-job",
          status: "queued",
          request: route.request().postDataJSON(),
        },
      });
    if (path === "/api/jobs/contract-test-job")
      return route.fulfill({
        json: {
          id: "contract-test-job",
          status: "failed",
          request: {},
          error: "No acceptable satellite observation",
        },
      });
    if (path === "/api/scenes")
      return route.fulfill({ json: { before: [], after: [] } });
    if (path === "/api/fire-observations")
      return route.fulfill({
        status: 503,
        json: { detail: "FIRMS_MAP_KEY is required" },
      });
    return route.fulfill({
      status: 404,
      json: { detail: "Test route not installed" },
    });
  });
});
test("a region starts analysis in one click with its own footprint and dates", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Bölge ara").fill("Izmir");
  const pending = page.waitForRequest(
    (r) => r.url().endsWith("/api/jobs") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "İzmir · Analiz et" }).click();
  const submitted = (await pending).postDataJSON();
  expect(submitted.before_start).toBe("2018-06-01");
  expect(submitted.after_start).toBe("2020-06-01");
  expect(submitted.geometry.coordinates[0][0]).toEqual([26.96, 38.13]);
  await expect(page.locator(".error[role=alert]")).toContainText(
    "uygun uydu görüntüsü yok",
  );
});
test("custom dates remain optional and reach the backend", async ({ page }) => {
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page.getByText("Tam tarih aralığı", { exact: true }).click();
  await page.getByLabel("Önceki dönem başlangıcı").fill("2019-06-01");
  await page.getByLabel("Önceki dönem sonu").fill("2019-06-30");
  const pending = page.waitForRequest(
    (r) => r.url().endsWith("/api/jobs") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  expect((await pending).postDataJSON().before_start).toBe("2019-06-01");
});
test("place search and two dates create a custom analysis", async ({
  page,
}) => {
  await page.route("**/api/places?*", (route) =>
    route.fulfill({
      json: {
        places: [
          {
            id: 1,
            name: "Deneme alanı",
            admin1: "UI fixture",
            latitude: 37,
            longitude: 28,
          },
        ],
      },
    }),
  );
  await page.goto("/");
  await page.getByLabel("Bölge ara").fill("Deneme");
  await page.getByRole("button", { name: "Haritada ara", exact: true }).click();
  await page.getByRole("button", { name: "Deneme alanı UI fixture" }).click();
  await page.getByLabel("Önceki tarih", { exact: true }).fill("2020-06-30");
  await page.getByLabel("Sonraki tarih", { exact: true }).fill("2022-06-30");
  const pending = page.waitForRequest(
    (r) => r.url().endsWith("/api/jobs") && r.method() === "POST",
  );
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  const body = (await pending).postDataJSON();
  expect(body.before_start).toBe("2020-06-01");
  expect(body.after_start).toBe("2022-06-01");
  expect(body.display_name).toBe("Deneme alanı");
  expect(body.geometry.coordinates[0][0][1]).toBeCloseTo(36.9775, 4);
});

for (const order of ["before-first", "after-first"]) {
  test(`comparison shorter than two years is rejected before submission (${order})`, async ({
    page,
  }) => {
    await page.goto("/");
    await page.locator(".new-analysis summary").click();
    const before = page.getByLabel("Önceki tarih", { exact: true });
    const after = page.getByLabel("Sonraki tarih", { exact: true });
    if (order === "before-first") {
      await before.fill("2020-06-30");
      await after.fill("2020-07-29");
    } else {
      await after.fill("2020-07-29");
      await before.fill("2020-06-30");
    }
    const posted: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST") posted.push(r.url());
    });
    await page.getByRole("button", { name: "Analizi başlat" }).click();
    await expect(page.locator(".error[role=alert]")).toContainText(
      "en az 2 yıl",
    );
    expect(posted).toEqual([]);
  });
}

test("reload opens the latest created analysis even for an earlier observation date", async ({
  page,
}) => {
  const records = [
    {
      id: "history-older",
      status: "succeeded",
      created_at: "2026-10-13T12:00:00Z",
      request: {
        display_name: "Eski inceleme",
        before_end: "2025-09-30",
        after_end: "2026-09-30",
      },
    },
    {
      id: "history-latest",
      status: "succeeded",
      created_at: "2026-10-14T12:00:00Z",
      request: {
        display_name: "Yeni inceleme",
        before_end: "2020-06-30",
        after_end: "2024-06-30",
      },
    },
  ];
  await page.route("**/api/jobs", (route) => route.fulfill({ json: records }));
  await page.route("**/api/jobs/history-*", (route) =>
    route.fulfill({
      json: records.find((r) => route.request().url().endsWith(r.id)),
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Yeni inceleme", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Yeni inceleme", exact: true }),
  ).toBeVisible();
  await page.getByText("Geçmiş sonuçlar", { exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: /Yeni inceleme.*30 Haz 2020.*30 Haz 2024/,
    }),
  ).toBeVisible();
});

test("reload preserves the latest failure instead of displaying an older success", async ({
  page,
}) => {
  const records = [
    {
      id: "latest-failed",
      status: "failed",
      created_at: "2026-10-15T10:00:00Z",
      request: { display_name: "Son deneme" },
      error: "No acceptable satellite observation",
    },
    {
      id: "older-success",
      status: "succeeded",
      created_at: "2026-10-14T10:00:00Z",
      request: { display_name: "Eski sonuç" },
    },
  ];
  await page.route("**/api/jobs", (r) => r.fulfill({ json: records }));
  await page.route(/\/api\/jobs\/(latest-failed|older-success)$/, (r) =>
    r.fulfill({ json: records.find((j) => r.request().url().endsWith(j.id)) }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Son deneme", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".error[role=alert]")).toContainText(
    "uygun uydu görüntüsü yok",
  );
});

test("an initial history request cannot overwrite a newer place selection", async ({
  page,
}) => {
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/jobs", async (r) => {
    await barrier;
    await r.fulfill({
      json: [
        {
          id: "slow-initial",
          status: "succeeded",
          created_at: "2026-10-14T10:00:00Z",
          request: {},
        },
      ],
    });
  });
  await page.route("**/api/jobs/slow-initial", (r) =>
    r.fulfill({
      json: {
        id: "slow-initial",
        status: "succeeded",
        request: { display_name: "Eski sonuç" },
      },
    }),
  );
  await page.route("**/api/places?*", (r) =>
    r.fulfill({
      json: {
        places: [{ id: 1, name: "Ankara", latitude: 39.92, longitude: 32.85 }],
      },
    }),
  );
  await page.goto("/");
  await page.getByLabel("Bölge ara").fill("Ankara");
  await page.getByRole("button", { name: "Haritada ara", exact: true }).click();
  await page.getByRole("button", { name: "Ankara", exact: true }).click();
  release();
  await expect(page.locator(".header-meta")).toContainText("Analiz açık");
  await expect(
    page.getByRole("heading", { name: "Ankara", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Eski sonuç", exact: true }),
  ).toHaveCount(0);
});

test("a lost admission response recovers the recorded job without a second POST", async ({
  page,
}) => {
  let recorded: Record<string, unknown> | undefined;
  let posts = 0;
  await page.route("**/api/jobs", async (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: recorded ? [recorded] : [] });
    posts++;
    recorded = {
      id: "recorded-after-timeout",
      status: "queued",
      created_at: new Date().toISOString(),
      request: route.request().postDataJSON(),
    };
    return route.fulfill({
      status: 503,
      json: {
        detail:
          "İşlem kaydedildi; gönderim doğrulanamadı. Geçmiş sonuçları kontrol edin.",
      },
    });
  });
  await page.route("**/api/jobs/recorded-after-timeout", (r) =>
    r.fulfill({ json: recorded }),
  );
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.locator(".execution-state")).toContainText("Analiz sırada");
  await expect(page.getByLabel("Önceki tarih", { exact: true })).toBeDisabled();
  expect(posts).toBe(1);
});

test("a recovered poll clears the temporary network warning", async ({
  page,
}) => {
  let polls = 0;
  await page.route("**/api/jobs/contract-test-job", (route) => {
    polls++;
    return polls === 1
      ? route.fulfill({ status: 503, json: { detail: "Server unavailable" } })
      : route.fulfill({
          json: {
            id: "contract-test-job",
            status: "running",
            stage: "before",
            request: {},
          },
        });
  });
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.locator(".error[role=alert]")).toContainText(
    "Bağlantı kurulamadı",
  );
  await expect(page.locator(".error[role=alert]")).toHaveCount(0, {
    timeout: 7000,
  });
});
test("optional catalogue and thermal failures use plain Turkish", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page
    .getByText("Görüntüleri önceden kontrol et", { exact: true })
    .click();
  await page.getByRole("button", { name: "Görüntü ara", exact: true }).click();
  await expect(page.getByText("Önce: 0 · Sonra: 0 görüntü")).toBeVisible();
  await page.getByText("Harita görünümü").click();
  await page
    .getByRole("button", { name: "Son 24 saat: sıcaklık gözlemleri" })
    .click();
  await expect(page.locator(".error[role=alert]")).toContainText(
    "Yangın gözlemleri şu anda kullanılamıyor",
  );
});
test("mobile drawing and layers work without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page.getByRole("button", { name: "Alan çiz" }).click();
  await expect(page.getByText("Alanın iki karşı köşesine dokun")).toBeVisible();
  await page.getByText("Harita görünümü").click();
  await page.getByLabel("Değişen alanlar").uncheck();
  await expect(page.getByLabel("Değişen alanlar")).not.toBeChecked();
  await page.getByLabel("Turuncu alanların görünürlüğü").fill("0.4");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect(
    page.getByRole("button", { name: "Methods & evidence" }),
  ).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("lang", "tr");
});

test("drawing is ready while external basemap tiles are still pending", async ({
  page,
}) => {
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("https://server.arcgisonline.com/**", async (route) => {
    await barrier;
    await route.abort();
  });
  try {
    await page.goto("/");
    await page.locator(".new-analysis summary").click();
    await page.getByRole("button", { name: "Serbest çiz" }).click();
    const canvas = page.locator(".maplibregl-canvas");
    await expect(canvas).toHaveCSS("cursor", "crosshair");
    await canvas.click({ position: { x: 150, y: 100 } });
    await expect(page.locator(".draw-hint [role=status]")).toContainText(
      "1 köşe",
    );
    await page.getByRole("button", { name: "Vazgeç", exact: true }).click();
    await expect(page.locator(".draw-hint")).toHaveCount(0);
  } finally {
    release();
  }
});
test("a crossing custom boundary stays editable and undo submits the corrected shape", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page.getByRole("button", { name: "Serbest çiz" }).click();
  const canvas = page.locator(".maplibregl-canvas");
  await expect(canvas).toBeVisible();
  await expect(canvas).toHaveCSS("cursor", "crosshair");
  const bounds = (await canvas.boundingBox())!;
  const corners = [
    { x: bounds.width * 0.32, y: bounds.height * 0.32 },
    { x: bounds.width * 0.62, y: bounds.height * 0.62 },
    { x: bounds.width * 0.32, y: bounds.height * 0.62 },
    { x: bounds.width * 0.62, y: bounds.height * 0.32 },
  ];
  for (const position of corners) await canvas.click({ position });
  await page.getByRole("button", { name: "Alanı bitir", exact: true }).click();
  await expect(page.locator(".draw-hint [role=alert]")).toContainText(
    "kesişiyor",
  );
  // The prior area cannot accidentally be submitted while this draft is invalid.
  let posts = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/jobs")) posts++;
  });
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  await expect(page.locator(".error[role=alert]")).toContainText(
    "çizimini bitirin",
  );
  expect(posts).toBe(0);
  await page.getByRole("button", { name: "Geri al", exact: true }).click();
  await page.getByRole("button", { name: "Alanı bitir", exact: true }).click();
  await expect(page.locator(".draw-hint")).toHaveCount(0);
  const pending = page.waitForRequest(
    (r) => r.method() === "POST" && r.url().endsWith("/api/jobs"),
  );
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  const ring = (await pending).postDataJSON().geometry.coordinates[0];
  expect(ring).toHaveLength(4);
  expect(ring[0]).toEqual(ring[3]);
  expect(new Set(ring.slice(0, -1).map(JSON.stringify)).size).toBe(3);
});

test("double-click completion adds the last corner only once", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.locator(".new-analysis summary").click();
  await page.getByRole("button", { name: "Serbest çiz" }).click();
  const canvas = page.locator(".maplibregl-canvas");
  await expect(canvas).toHaveCSS("cursor", "crosshair");
  const b = (await canvas.boundingBox())!;
  await canvas.click({ position: { x: b.width * 0.32, y: b.height * 0.32 } });
  await canvas.click({ position: { x: b.width * 0.62, y: b.height * 0.32 } });
  await canvas.dblclick({
    position: { x: b.width * 0.62, y: b.height * 0.62 },
  });
  await expect(page.locator(".draw-hint")).toHaveCount(0);
  const pending = page.waitForRequest(
    (r) => r.method() === "POST" && r.url().endsWith("/api/jobs"),
  );
  await page.getByRole("button", { name: "Analizi başlat" }).click();
  expect((await pending).postDataJSON().geometry.coordinates[0]).toHaveLength(
    4,
  );
});
test("completed comparison, adjacent terminology and valid CSV download", async ({
  page,
}) => {
  const geometry = {
    type: "Polygon",
    coordinates: [
      [
        [28.22, 36.98],
        [28.35, 36.98],
        [28.35, 37.1],
        [28.22, 37.1],
        [28.22, 36.98],
      ],
    ],
  };
  const record = {
    id: "ui-contract-complete",
    status: "succeeded",
    created_at: "2026-10-14T10:00:00Z",
    request: {
      geometry,
      before_start: "2020-06-01",
      before_end: "2020-06-30",
      after_start: "2022-06-01",
      after_end: "2022-06-30",
    },
    report: {
      geometry,
      bounds: [28.22, 36.98, 28.35, 37.1],
      generated_at: "2026-10-14T10:00:00Z",
      source_observations: [
        { scene_id: "UI_TEST_A", acquired_at: "2020-06-15T09:00:00Z" },
        { scene_id: "UI_TEST_B", acquired_at: "2022-06-15T09:00:00Z" },
      ],
      model_version: "ui-contract-only",
      clear_fraction: 1,
      mapped_candidate_area_ha: 0,
      candidate_polygons: 0,
      indices: { ndvi: { before_mean: 0, after_mean: 0, delta_mean: 0 } },
      interpretation: "UI fixture only",
      limitations: ["Synthetic UI fixture"],
    },
  };
  await page.route("**/api/jobs", (r) => r.fulfill({ json: [record] }));
  await page.route("**/api/jobs/ui-contract-complete", (r) =>
    r.fulfill({ json: record }),
  );
  await page.route("**/api/jobs/ui-contract-complete/export/csv", (r) =>
    r.fulfill({
      contentType: "text/csv",
      headers: { "Content-Disposition": "attachment; filename=contract.csv" },
      body: "fixture_only\ntrue\n",
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Marmaris · Orman değişimi" }),
  ).toBeVisible();
  await page.getByLabel("Önce ve sonra karşılaştırması").fill("25");
  await expect(page.locator(".before-image")).toHaveCSS(
    "clip-path",
    "inset(0px 75% 0px 0px)",
  );
  await page.getByText("Ayrıntılar ve dosyalar", { exact: true }).click();
  await expect(
    page.getByText("NDVI · Bitki örtüsünün ne kadar yeşil göründüğü."),
  ).toBeVisible();
  const pending = page.waitForEvent("download");
  await page.getByRole("link", { name: "Tablo (CSV)", exact: true }).click();
  expect((await pending).suggestedFilename()).toBe("contract.csv");
  await page.locator(".new-analysis summary").click();
  await expect(page.locator(".comparison")).toHaveCount(0);
});
