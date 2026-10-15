import { expect, test } from "@playwright/test";
import { privateResponse, handleHostedApi } from "../lib/hosted-api";

test("large private downloads retain their signed redirect and session headers", () => {
  const original = Response.redirect(
    "https://example.com/private-test-artifact",
    307,
  );
  expect(() => original.headers.set("Cache-Control", "private")).toThrow();
  const response = privateResponse(original, "test_session=fixture; HttpOnly");
  expect(response.status).toBe(307);
  expect(response.headers.get("location")).toBe(
    "https://example.com/private-test-artifact",
  );
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  expect(response.headers.get("set-cookie")).toBe(
    "test_session=fixture; HttpOnly",
  );
});

test("an unsuccessful first request retains its signed session cookie", async () => {
  const previous = { ...process.env };
  const originalFetch = globalThis.fetch;
  Object.assign(process.env, {
    ECOSENTINEL_CLOUD_ANALYSIS: "1",
    ECOSENTINEL_BACKEND_URL: "https://compute.example.test",
    ECOSENTINEL_BACKEND_TOKEN: "fixture-only",
    BLOB_STORE_ID: "fixture-only",
  });
  globalThis.fetch = async () =>
    Response.json(
      { ok: false, detail: "temporary infrastructure error" },
      { status: 503 },
    );
  try {
    const response = await handleHostedApi(
      new Request("http://localhost/api/scenes", {
        method: "POST",
        body: "{}",
      }),
      "/api/scenes",
    );
    expect(response.status).toBe(503);
    expect(response.headers.get("set-cookie")).toContain(
      "ecosentinel_session=",
    );
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  } finally {
    globalThis.fetch = originalFetch;
    for (const key of Object.keys(process.env))
      if (!(key in previous)) delete process.env[key];
    Object.assign(process.env, previous);
  }
});
