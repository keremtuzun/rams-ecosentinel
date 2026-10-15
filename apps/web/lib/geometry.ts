import type { Geometry } from "./api";

const same = (a: number[], b: number[]) => a[0] === b[0] && a[1] === b[1];
const cross = (a: number[], b: number[], c: number[]) =>
  (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
const onSegment = (a: number[], b: number[], p: number[]) =>
  Math.abs(cross(a, b, p)) < 1e-12 &&
  p[0] >= Math.min(a[0], b[0]) &&
  p[0] <= Math.max(a[0], b[0]) &&
  p[1] >= Math.min(a[1], b[1]) &&
  p[1] <= Math.max(a[1], b[1]);

export const polygonDrawingError =
  "Sınır çizgileri kesişiyor veya üst üste geliyor. Geri al ile son köşeyi düzeltin.";

// Check the closing edge too. Never reshape a user's boundary to make it valid.
export function geometryError(geometry: Geometry): string {
  const ring = geometry.coordinates[0];
  if (!ring || ring.length < 4 || !same(ring[0], ring[ring.length - 1]))
    return "En az 3 köşe seçip Alanı bitir’e dokunun.";
  if (geometry.coordinates.flat().length > 200)
    return "En fazla 199 köşe seçin. Geri al ile son köşeyi kaldırın.";
  if (ring.some((p) => p.length !== 2 || !p.every(Number.isFinite)))
    return "Alan okunamadı. Haritadan yeniden çizin.";
  const n = ring.length - 1;
  for (let i = 0; i < n; i++) {
    const a = ring[i],
      b = ring[i + 1],
      c = ring[(i + 2) % n];
    if (
      same(a, b) ||
      (Math.abs(cross(a, b, c)) < 1e-12 &&
        (onSegment(a, b, c) || onSegment(b, c, a)))
    )
      return polygonDrawingError;
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue;
      const c = ring[j],
        d = ring[j + 1];
      if (
        (cross(a, b, c) * cross(a, b, d) < 0 &&
          cross(c, d, a) * cross(c, d, b) < 0) ||
        onSegment(a, b, c) ||
        onSegment(a, b, d) ||
        onSegment(c, d, a) ||
        onSegment(c, d, b)
      )
        return polygonDrawingError;
    }
  }
  return "";
}
