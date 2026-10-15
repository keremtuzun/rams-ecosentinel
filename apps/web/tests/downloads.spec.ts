import { expect, test } from "@playwright/test";
import { privateResponse } from "../lib/hosted-api";

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
