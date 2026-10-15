import { expect, test } from "@playwright/test";
import { geometryError } from "../lib/geometry";
import { simpleError } from "../lib/presentation";

const check = (ring: number[][]) =>
  geometryError({ type: "Polygon", coordinates: [ring] });

test("a valid concave boundary keeps its exact shape", () => {
  expect(
    check([
      [31, 37],
      [31.1, 37],
      [31.05, 37.05],
      [31.1, 37.1],
      [31, 37.1],
      [31, 37],
    ]),
  ).toBe("");
  // A redundant straight-line vertex is harmless, a backtracking edge is not.
  expect(
    check([
      [31, 37],
      [31.05, 37],
      [31.1, 37],
      [31.1, 37.1],
      [31, 37.1],
      [31, 37],
    ]),
  ).toBe("");
});

test("crossings, a crossing closing edge and backtracking are rejected", () => {
  for (const ring of [
    [
      [31, 37],
      [31.1, 37.1],
      [31, 37.1],
      [31.1, 37],
      [31, 37],
    ],
    [
      [31, 37],
      [31.1, 37],
      [31.1, 37.1],
      [31.2, 37.1],
      [31.2, 37.05],
      [31, 37],
    ],
    [
      [31, 37],
      [31.1, 37],
      [31.05, 37],
      [31.1, 37.1],
      [31, 37.1],
      [31, 37],
    ],
    [
      [31, 37],
      [31.1, 37],
      [31.1, 37],
      [31.1, 37.1],
      [31, 37],
    ],
  ])
    expect(check(ring)).toContain("kesişiyor");
});

test("the server's invalid polygon error explains how to correct the drawing", () => {
  expect(simpleError("AOI must be a valid, nonempty Polygon")).toContain(
    "Çizgiler kesişmeden",
  );
  expect(simpleError("AOI is limited to 200 vertices")).toContain(
    "Daha az köşeyle",
  );
});
