import { expect, test } from "@playwright/test";
import { comparisonWindows, comparisonDateError } from "../lib/dates";
import { simpleError } from "../lib/presentation";

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
