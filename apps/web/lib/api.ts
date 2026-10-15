export const API = process.env.NEXT_PUBLIC_API_URL ?? "";
export type Geometry = { type: "Polygon"; coordinates: number[][][] };
export type Region = {
  id: string;
  name: string;
  split: string;
  bbox: number[];
  before: string[];
  after: string[];
  loss_year: number;
};
export type Source = {
  scene_id: string;
  acquired_at: string;
  source: string;
  clear_fraction: number;
  acquisition_range?: string[];
};
export type Report = {
  generated_at: string;
  bounds: number[];
  corners?: number[][];
  geometry: Geometry;
  source_observations: Source[];
  model_version: string;
  clear_fraction: number;
  eligible_pixels: number;
  candidate_pixels: number;
  mapped_candidate_area_ha: number;
  candidate_polygons: number;
  latest_observation_age_days: number;
  indices: Record<
    string,
    { before_mean: number; after_mean: number; delta_mean: number }
  >;
  uncertainty?: {
    status: string;
    method?: string;
    mean_disagreement_on_eligible_pixels: number | null;
    p95_disagreement_on_eligible_pixels: number | null;
    meaning?: string;
  };
  interpretation: string;
  limitations: string[];
};
export type Job = {
  stage?: string;
  id: string;
  status: string;
  created_at: string;
  updated_at: string;
  attempts: number;
  error: string | null;
  request: Record<string, unknown>;
  report?: Report;
};
export function rectangle(b: number[]): Geometry {
  return {
    type: "Polygon",
    coordinates: [
      [
        [b[0], b[1]],
        [b[2], b[1]],
        [b[2], b[3]],
        [b[0], b[3]],
        [b[0], b[1]],
      ],
    ],
  };
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    API + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(
      response.ok
        ? "Invalid server response"
        : `Server unavailable (${response.status})`,
    );
  }
  if (!response.ok) {
    const detail = result.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join("; ")
          : "Request failed",
    );
  }
  return result as T;
}
