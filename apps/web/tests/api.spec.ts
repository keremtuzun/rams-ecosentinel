import { expect, test } from "@playwright/test";
import { api } from "../lib/api";
import { simpleError } from "../lib/presentation";

test("HTML gateway errors retain a useful Turkish network explanation", async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response("<html>Gateway timeout</html>", { status: 504 });
  try {
    await expect(api("/api/jobs")).rejects.toThrow("Server unavailable (504)");
    expect(simpleError("Server unavailable (504)")).toContain(
      "Bağlantı kurulamadı",
    );
  } finally {
    globalThis.fetch = previous;
  }
});
