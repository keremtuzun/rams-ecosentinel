import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fromFile } from "geotiff";
import proj4 from "proj4";
import {
  backendRpc,
  cloudEnabled,
  cloudFile,
  cloudHealth,
  cloudInspect,
  cloudJob,
  cloudJobs,
  CloudError,
  createCloudJob,
  getSession,
} from "./cloud-analysis";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ASSETS = new Set([
  "before.png",
  "after.png",
  "overlay.png",
  "map.png",
  "score.tif",
  "mask.tif",
  "indices.tif",
  "source_before_index.tif",
  "source_after_index.tif",
  "uncertainty.tif",
  "change.geojson",
  "report.json",
]);
const BASE = join(process.cwd(), "public", "evidence");

function error(detail: string, status = 503) {
  return Response.json({ detail }, { status });
}

export function privateResponse(response: Response, cookie: string | null) {
  // Native redirect headers are immutable. Clone the headers rather than
  // mutating the signed download redirect returned by private Blob storage.
  const headers = new Headers(response.headers);
  if (cookie) headers.set("Set-Cookie", cookie);
  headers.set("Cache-Control", "private, no-store");
  return new Response(response.body, { status: response.status, headers });
}

export async function handleHostedApi(
  request: Request,
  path: string,
): Promise<Response> {
  const cloud = cloudEnabled();
  if (cloud) {
    let cookie: string | null = null;
    try {
      const session = getSession(
        request,
        path === "/health" || request.method === "POST",
      );
      cookie = session.cookie;
      const respond = (response: Response) => {
        return privateResponse(response, session.cookie);
      };
      if (path === "/health") {
        const health = await cloudHealth();
        return respond(
          Response.json({
            status: "ok",
            mode: "cloud",
            analysis_available: true,
            engine: health.engine,
            limits: {
              country: "TR",
              max_area_km2: 2500,
              max_side_km: 50,
              min_comparison_years: 2,
              per_session_per_hour: 3,
              global_per_hour: 8,
            },
          }),
        );
      }
      if (request.method === "POST") {
        const origin = request.headers.get("origin"),
          host = request.headers.get("host");
        if (origin && new URL(origin).host !== host)
          return error("Bu işlem yalnızca aynı siteden başlatılabilir", 403);
        const bytes = await request.arrayBuffer();
        if (bytes.byteLength > 16384) return error("İstek çok büyük", 413);
        let body: unknown;
        try {
          body = JSON.parse(new TextDecoder().decode(bytes));
        } catch {
          return error("Geçersiz istek", 400);
        }
        if (path === "/api/jobs")
          return respond(
            Response.json(await createCloudJob(session.id!, body), {
              status: 202,
            }),
          );
        if (path === "/api/scenes")
          return respond(
            Response.json(
              await backendRpc({ action: "scenes", request: body }),
            ),
          );
        return error("Bu özellik şu anda kullanılamıyor", 503);
      }
      const catalog = JSON.parse(
        await readFile(join(BASE, "catalog.json"), "utf8"),
      );
      if (path === "/api/jobs") {
        const created = await cloudJobs(session.id);
        const stored = catalog.jobs.map((j: { report?: unknown }) => {
          const { report, ...record } = j;
          void report;
          return record;
        });
        return respond(Response.json([...created, ...stored]));
      }
      const route =
        /^\/api\/jobs\/([^/]+)(?:\/(files|export|inspect)(?:\/([^/]+))?)?$/.exec(
          path,
        );
      if (
        route &&
        UUID.test(route[1]) &&
        !catalog.jobs.some((j: { id: string }) => j.id === route[1])
      ) {
        if (!route[2]) {
          const record = await cloudJob(session.id, route[1]);
          return record
            ? respond(Response.json(record))
            : error("Sonuç bulunamadı", 404);
        }
        if (route[2] === "inspect")
          return respond(await cloudInspect(session.id, route[1], request));
        let name = route[3];
        if (route[2] === "export")
          name = (
            {
              pdf: "assessment.pdf",
              csv: "assessment.csv",
              json: "report.json",
              geojson: "change.geojson",
            } as Record<string, string>
          )[name];
        else if (!ASSETS.has(name)) return error("Dosya bulunamadı", 404);
        if (!name) return error("Dosya bulunamadı", 404);
        return respond(await cloudFile(session.id, route[1], name));
      }
    } catch (exc) {
      console.error(
        JSON.stringify({
          event: "cloud_api_failed",
          path,
          type: exc instanceof Error ? exc.name : "unknown",
        }),
      );
      return privateResponse(
        error(
          exc instanceof CloudError
            ? exc.message
            : "Analiz sunucusu şu anda kullanılamıyor",
          exc instanceof CloudError ? exc.status : 503,
        ),
        cookie,
      );
    }
  }
  const configured = process.env.ECOSENTINEL_BACKEND_URL;
  const backend = cloud
    ? undefined
    : configured ||
      (!process.env.VERCEL && process.env.ECOSENTINEL_HOSTED_MODE !== "evidence"
        ? "http://127.0.0.1:8000"
        : undefined);
  if (backend) {
    // Backend origin is trusted server configuration, never a request parameter or client secret.
    const destination = new URL(backend);
    if (process.env.VERCEL && destination.protocol !== "https:")
      return error("Hosted backend must use HTTPS");
    if (destination.username || destination.password)
      return error("Backend credentials must use server-side headers");
    destination.pathname = path;
    destination.search = new URL(request.url).search;
    let body: ArrayBuffer | undefined;
    if (request.method === "POST") {
      body = await request.arrayBuffer();
      if (body.byteLength > 16384) return error("Request exceeds 16 KB", 413);
    }
    const headers = new Headers({ "Content-Type": "application/json" });
    if (process.env.ECOSENTINEL_BACKEND_TOKEN)
      headers.set(
        "Authorization",
        `Bearer ${process.env.ECOSENTINEL_BACKEND_TOKEN}`,
      );
    try {
      const upstream = await fetch(destination, {
        method: request.method,
        headers,
        body,
        redirect: "error",
        signal: AbortSignal.timeout(60000),
        cache: "no-store",
      });
      const responseHeaders = new Headers();
      for (const name of ["content-type", "content-disposition"]) {
        const value = upstream.headers.get(name);
        if (value) responseHeaders.set(name, value);
      }
      responseHeaders.set("Cache-Control", "no-store");
      return new Response(upstream.body, {
        status: upstream.status,
        headers: responseHeaders,
      });
    } catch {
      console.error(JSON.stringify({ event: "backend_unavailable", path }));
      return error(
        "The configured analysis backend is unavailable; no results were substituted",
      );
    }
  }
  // Vercel is stateless: publish actual completed evidence, never pretend local jobs can run here.
  if (path === "/health") {
    try {
      await readFile(join(BASE, "catalog.json"));
      return Response.json({
        status: "ok",
        mode: "evidence",
        analysis_available: false,
        reason:
          "Recorded real analyses are available. New inference requires a hosted Python API and durable worker.",
      });
    } catch {
      return error("The evidence package is not installed");
    }
  }
  if (request.method !== "GET")
    return error(
      "New acquisition and model inference require a hosted Python backend; this release serves completed real analyses",
    );
  try {
    const catalog = JSON.parse(
      await readFile(join(BASE, "catalog.json"), "utf8"),
    );
    if (path === "/api/regions") return Response.json(catalog.regions);
    if (path === "/api/models") return Response.json(catalog.models);
    if (path === "/api/jobs")
      return Response.json(
        catalog.jobs.map((j: { report?: unknown }) => {
          const { report, ...record } = j;
          void report;
          return record;
        }),
      );
    const match =
      /^\/api\/jobs\/([^/]+)(?:\/(files|export|inspect)(?:\/([^/]+))?)?$/.exec(
        path,
      );
    if (!match || !UUID.test(match[1])) return error("Route not found", 404);
    const job = catalog.jobs.find((j: { id: string }) => j.id === match[1]);
    if (!job) return error("Job not found", 404);
    if (!match[2]) return Response.json(job);
    if (match[2] === "inspect") {
      const query = new URL(request.url).searchParams;
      const lon = Number(query.get("longitude")),
        lat = Number(query.get("latitude"));
      if (
        !query.has("longitude") ||
        !query.has("latitude") ||
        !Number.isFinite(lon) ||
        !Number.isFinite(lat) ||
        Math.abs(lon) > 180 ||
        Math.abs(lat) > 90
      )
        return error("Coordinates must be finite longitude/latitude", 422);
      const grid = job.report.grid;
      const utm = /^EPSG:326(\d{2})$/.exec(grid.crs);
      if (!utm) return error("Unsupported recorded projection");
      const [x, y] = proj4(
        "EPSG:4326",
        `+proj=utm +zone=${Number(utm[1])} +datum=WGS84 +units=m +no_defs`,
        [lon, lat],
      );
      const [a, b, c, d, e, f] = grid.transform;
      if (b !== 0 || d !== 0) return error("Unsupported recorded affine grid");
      const col = Math.floor((x - c) / a),
        row = Math.floor((y - f) / e);
      if (row < 0 || col < 0 || row >= grid.height || col >= grid.width)
        return error("Coordinates outside analysis grid", 422);
      const tiff = await fromFile(join(BASE, "jobs", job.id, "score.tif"));
      try {
        const raster = await tiff.getImage();
        const values = await raster.readRasters({
          window: [col, row, col + 1, row + 1],
          samples: [0],
          interleave: true,
        });
        const score = Number(values[0]);
        if (score === raster.getGDALNoData() || !Number.isFinite(score))
          return Response.json({
            score: null,
            meaning: "Masked or outside forest-like domain",
          });
        return Response.json({
          score,
          meaning: "uncalibrated annual forest-loss-reference score",
          resolution_m: 30,
        });
      } finally {
        await tiff.close();
      }
    }
    let name = match[3];
    if (match[2] === "export") {
      const exports: Record<string, string> = {
        pdf: "assessment.pdf",
        csv: "assessment.csv",
        geojson: "change.geojson",
        json: "report.json",
      };
      name = exports[name];
    } else if (!ASSETS.has(name)) return error("Artifact not found", 404);
    if (!name) return error("Unsupported export", 404);
    // Static downloads avoid Function response limits for multi-megabyte scientific GeoTIFFs.
    return new Response(null, {
      status: 307,
      headers: { Location: `/evidence/jobs/${job.id}/${name}` },
    });
  } catch (exc) {
    console.error(
      JSON.stringify({
        event: "evidence_read_failed",
        type: exc instanceof Error ? exc.name : "unknown",
      }),
    );
    return error(
      "Recorded evidence is unavailable; no placeholder results were substituted",
    );
  }
}
