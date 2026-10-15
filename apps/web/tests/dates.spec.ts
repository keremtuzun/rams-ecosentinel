import { expect, test } from "@playwright/test";
import { comparisonWindows, comparisonDateError } from "../lib/dates";
import { dateLabel, simpleError } from "../lib/presentation";

test("adjacent dates preserve endpoints and 2017 boundary without overlap", () => {
  expect(comparisonWindows("2017-01-01", "2017-01-02")).toEqual({
    before_start: "2017-01-01",
    before_end: "2017-01-01",
    after_start: "2017-01-02",
    after_end: "2017-01-02",
  });
  expect(comparisonWindows("2020-02-29", "2020-03-01").after_start).toBe(
    "2020-03-01",
  );
});

test("date display does not depend on browser language or local midnight", () => {
  expect(dateLabel("2020-02-29")).toBe("29 Şub 2020");
  expect(dateLabel("2020-06-30T23:59:00Z")).toBe("30 Haz 2020");
  expect(
    comparisonDateError(
      comparisonWindows("2022-06-30", "2024-06-30"),
      "2024-06-29",
    ),
  ).toContain("bugünü");
  expect(
    comparisonDateError(
      comparisonWindows("2022-06-30", "2024-06-30"),
      "2024-06-30",
    ),
  ).toBe("");
});

test("two-year comparison uses calendar anniversaries, including leap days", () => {
  expect(
    comparisonDateError(comparisonWindows("2020-06-30", "2022-06-29")),
  ).toContain("2 yıl");
  expect(
    comparisonDateError(comparisonWindows("2020-06-30", "2022-06-30")),
  ).toBe("");
  expect(
    comparisonDateError(comparisonWindows("2020-02-29", "2022-02-28")),
  ).toBe("");
});

test("each server date rejection states its actual cause", () => {
  expect(simpleError("The two observation windows must not overlap")).toContain(
    "çakışıyor",
  );
  expect(
    simpleError("Each scene-search window is limited to 62 days"),
  ).toContain("62 gün");
  expect(simpleError("Comparison interval cannot exceed ten years")).toContain(
    "10 yıl",
  );
  expect(
    simpleError(
      "Date ranges must be ordered, in the past, and start in 2017 or later",
    ),
  ).toContain("bugünü aşmayan");
});

test("client validates complete real date windows before sending them", () => {
  for (const dates of [
    { ...comparisonWindows("2020-06-30", "2022-06-30"), before_start: "" },
    comparisonWindows("2020-02-30", "2022-03-01"),
    comparisonWindows("2028-06-30", "2030-06-30"),
    {
      ...comparisonWindows("2020-06-30", "2022-06-30"),
      before_start: "2020-01-01",
    },
    comparisonWindows("2020-06-30", "2022-12-30"),
  ])
    expect(comparisonDateError(dates)).not.toBe("");
});
