import {
  createHmac,
  randomBytes,
  randomUUID,
  timingSafeEqual,
} from "node:crypto";
import {
  get,
  list,
  put,
  BlobPreconditionFailedError,
  issueSignedToken,
  presignUrl,
} from "@vercel/blob";
import { send } from "@vercel/queue";
import { fromArrayBuffer } from "geotiff";
import proj4 from "proj4";
import type { Job, Report } from "./api";

export const TOPIC = "ecosentinel-analysis-v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SESSION = /^[0-9a-f]{32}$/;
const COOKIE = "ecosentinel_session";
const STAGES = ["before", "after", "infer"] as const;
type Stage = (typeof STAGES)[number];
type Reference = { path: string; sha256: string; size: number };
export type CloudState = Job & {
  session: string;
  stage: Stage;
  stage_attempts: number;
  lease?: { owner: string; until: number };
  observations: Record<string, unknown>;
  files?: Record<string, Reference>;
  report?: Report & {
    grid: { crs: string; transform: number[]; height: number; width: number };
  };
};
export type StageMessage = { id: string; session: string; stage: Stage };
type Versioned = { body: CloudState; etag: string };
export type CloudPorts = {
  read: (key: string) => Promise<Versioned | null>;
  write: (key: string, body: CloudState, etag?: string) => Promise<string>;
  rpc: (body: unknown) => Promise<Record<string, unknown>>;
  enqueue: (message: StageMessage) => Promise<void>;
};
export class CloudError extends Error {
  constructor(
    message: string,
    public status = 503,
  ) {
    super(message);
  }
}

export function validIdentity(session: string, id: string) {
  return SESSION.test(session) && UUID.test(id);
}
function keyOf(session: string, id: string) {
  if (!validIdentity(session, id))
    throw new CloudError("Sonuç bulunamadı", 404);
  return `records/${session}/${id}.json`;
}
function signingKey() {
  const key = process.env.ECOSENTINEL_BACKEND_TOKEN;
  if (!key) throw new CloudError("Analiz sunucusu yapılandırılmadı");
  return key;
}
export function getSession(request: Request, create = false) {
  const value = request.headers
    .get("cookie")
    ?.split(";")
    .map((x) => x.trim())
    .find((x) => x.startsWith(COOKIE + "="))
    ?.slice(COOKIE.length + 1);
  if (value) {
    const [id, expires, signature] = value.split(".");
    if (
      SESSION.test(id || "") &&
      /^\d+$/.test(expires || "") &&
      Number(expires) > Date.now() &&
      Number(expires) < Date.now() + 31 * 86400000
    ) {
      const expected = createHmac("sha256", signingKey())
        .update(`${id}.${expires}`)
        .digest("base64url");
      if (
        signature &&
        signature.length === expected.length &&
        timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
      )
        return { id, cookie: null };
    }
  }
  if (!create) return { id: null, cookie: null };
  const id = randomBytes(16).toString("hex"),
    expires = Date.now() + 30 * 86400000;
  const signature = createHmac("sha256", signingKey())
    .update(`${id}.${expires}`)
    .digest("base64url");
  return {
    id,
    cookie: `${COOKIE}=${id}.${expires}.${signature}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000${process.env.VERCEL ? "; Secure" : ""}`,
  };
}
export function cloudEnabled() {
  return (
    process.env.ECOSENTINEL_CLOUD_ANALYSIS === "1" &&
    !!process.env.ECOSENTINEL_BACKEND_URL &&
    !!process.env.ECOSENTINEL_BACKEND_TOKEN &&
    !!process.env.BLOB_STORE_ID
  );
}
async function jsonBlob<T>(
  key: string,
): Promise<{ body: T; etag: string } | null> {
  // Compression changes GET's ETag into a weak validator. Blob's conditional
  // writes require the strong validator for the same bytes we just read.
  const result = await get(key, {
    access: "private",
    useCache: false,
    headers: { "Accept-Encoding": "identity" },
  });
  if (!result || !result.stream) return null;
  if (!result.blob.etag || result.blob.etag.startsWith("W/"))
    throw new CloudError("Depolama sürümü doğrulanamadı");
  return {
    body: JSON.parse(await new Response(result.stream).text()),
    etag: result.blob.etag,
  };
}
async function writeBlob(key: string, body: unknown, etag?: string) {
  const result = await put(key, JSON.stringify(body), {
    access: "private",
    addRandomSuffix: false,
    allowOverwrite: !!etag,
    ifMatch: etag,
    contentType: "application/json",
  });
  return result.etag;
}
export async function backendRpc(
  body: unknown,
): Promise<Record<string, unknown>> {
  const origin = new URL(process.env.ECOSENTINEL_BACKEND_URL!);
  if (origin.protocol !== "https:" && process.env.VERCEL)
    throw new CloudError("Analiz sunucusu HTTPS kullanmalı");
  origin.pathname = "/rpc";
  origin.search = "";
  const response = await fetch(origin, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${signingKey()}`,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(270000),
    cache: "no-store",
    redirect: "error",
  });
  const result = await response.json();
  if (!response.ok || result.ok !== true)
    throw new CloudError(
      typeof result.detail === "string"
        ? result.detail
        : "Analiz tamamlanamadı",
      response.status === 422 ? 422 : 503,
    );
  return result.result;
}
async function enqueue(message: StageMessage) {
  await send(TOPIC, message, {
    idempotencyKey: `${message.id}-${message.stage}`,
    retentionSeconds: 86400,
  });
}
const defaultPorts: CloudPorts = {
  read: jsonBlob<CloudState>,
  write: writeBlob,
  rpc: backendRpc,
  enqueue,
};

export async function processCloudStage(
  message: StageMessage,
  ports: CloudPorts = defaultPorts,
) {
  if (
    !validIdentity(message.session, message.id) ||
    !STAGES.includes(message.stage)
  )
    throw new CloudError("Invalid queue message", 400);
  const key = keyOf(message.session, message.id),
    current = await ports.read(key);
  if (!current) throw new Error("Queue record is not available");
  const state = current.body;
  if (["succeeded", "failed"].includes(state.status)) return;
  const stage = STAGES.indexOf(state.stage),
    incoming = STAGES.indexOf(message.stage);
  if (incoming < stage) {
    await ports.enqueue({
      id: state.id,
      session: state.session,
      stage: state.stage,
    });
    return;
  }
  if (incoming > stage || (state.lease && state.lease.until > Date.now()))
    throw new Error("Stage is not ready or leased");
  if (state.stage_attempts >= 2) {
    await ports.write(
      key,
      {
        ...state,
        status: "failed",
        error: "Sunucu işlemi iki denemede tamamlayamadı",
        updated_at: new Date().toISOString(),
        lease: undefined,
      },
      current.etag,
    );
    return;
  }
  const owner = randomUUID();
  const claimed: CloudState = {
    ...state,
    status: "running",
    attempts: state.attempts + 1,
    stage_attempts: state.stage_attempts + 1,
    updated_at: new Date().toISOString(),
    lease: { owner, until: Date.now() + 310000 },
  };
  const etag = await ports.write(key, claimed, current.etag);
  let result: Record<string, unknown>;
  try {
    result = await ports.rpc({
      action: state.stage,
      id: state.id,
      session: state.session,
      owner,
      request: state.request,
      observations: state.observations,
    });
  } catch (error) {
    if (error instanceof CloudError && error.status === 422) {
      await ports.write(
        key,
        {
          ...claimed,
          status: "failed",
          lease: undefined,
          error: error.message,
          updated_at: new Date().toISOString(),
        },
        etag,
      );
      return;
    }
    throw error;
  }
  const next: CloudState = {
    ...claimed,
    updated_at: new Date().toISOString(),
    lease: undefined,
  };
  if (state.stage === "infer") {
    if (!result.report || !result.files)
      throw new Error("Compute did not return genuine artifacts");
    next.status = "succeeded";
    next.error = null;
    next.report = result.report as CloudState["report"];
    next.files = result.files as Record<string, Reference>;
    for (const reference of Object.values(next.files))
      if (
        !reference.path.startsWith(
          `analysis/${state.session}/${state.id}/${owner}/`,
        ) ||
        !/^\w[\w.]*$/.test(reference.path.split("/").at(-1)!)
      )
        throw new Error("Invalid result artifact ownership");
  } else {
    for (const kind of ["data", "metadata"]) {
      const reference = result[kind] as Reference;
      if (
        !reference ||
        !reference.path.startsWith(
          `analysis/${state.session}/${state.id}/${owner}/`,
        ) ||
        !/^[0-9a-f]{64}$/.test(reference.sha256)
      )
        throw new Error("Invalid observation artifact ownership");
    }
    next.observations = { ...claimed.observations, [state.stage]: result };
    next.stage = STAGES[stage + 1];
    next.stage_attempts = 0;
  }
  await ports.write(key, next, etag);
  if (next.status !== "succeeded")
    await ports.enqueue({
      id: next.id,
      session: next.session,
      stage: next.stage,
    });
}

type QuotaState = { ids: string[]; sessions: Record<string, number> };
type QuotaPorts = {
  read: (key: string) => Promise<{ body: QuotaState; etag: string } | null>;
  write: (key: string, body: QuotaState, etag?: string) => Promise<string>;
};
export async function reserveQuota(
  id: string,
  session: string,
  ports: QuotaPorts = { read: jsonBlob<QuotaState>, write: writeBlob },
) {
  const hour = new Date().toISOString().slice(0, 13),
    key = `limits/${hour}.json`;
  for (let attempt = 0; attempt < 4; attempt++) {
    const current = await ports.read(key),
      value = current?.body || { ids: [], sessions: {} };
    if (value.ids.includes(id)) return;
    if (value.ids.length >= 8 || (value.sessions[session] || 0) >= 3)
      throw new CloudError(
        "Analiz kotası doldu. Bir sonraki saatte tekrar deneyin.",
        429,
      );
    try {
      await ports.write(
        key,
        {
          ids: [...value.ids, id],
          sessions: {
            ...value.sessions,
            [session]: (value.sessions[session] || 0) + 1,
          },
        },
        current?.etag,
      );
      return;
    } catch (error) {
      if (
        !(error instanceof BlobPreconditionFailedError) &&
        !(error instanceof Error && /already exists/i.test(error.message))
      )
        throw error;
    }
  }
  throw new CloudError("Sunucu meşgul. Tekrar deneyin.", 429);
}
function publicJob(state: CloudState) {
  const { session, stage_attempts, lease, observations, files, ...record } =
    state;
  void session;
  void stage_attempts;
  void lease;
  void observations;
  void files;
  return record;
}
export async function createCloudJob(session: string, body: unknown) {
  const validated = await backendRpc({ action: "validate", request: body });
  const id = randomUUID();
  await reserveQuota(id, session);
  const timestamp = new Date().toISOString();
  const state: CloudState = {
    id,
    session,
    stage: "before",
    stage_attempts: 0,
    observations: {},
    request: {
      ...(validated.request as Record<string, unknown>),
      display_name:
        typeof (body as Record<string, unknown>)?.display_name === "string"
          ? String((body as Record<string, unknown>).display_name).slice(0, 80)
          : undefined,
    },
    status: "queued",
    created_at: timestamp,
    updated_at: timestamp,
    attempts: 0,
    error: null,
  };
  const key = keyOf(session, id);
  await writeBlob(key, state);
  try {
    await enqueue({ id, session, stage: "before" });
  } catch {
    console.error(
      JSON.stringify({ event: "queue_dispatch_unknown", job_id: id }),
    );
    throw new CloudError(
      "İşlem kaydedildi; gönderim doğrulanamadı. Geçmiş sonuçları kontrol edin.",
    );
  }
  return publicJob(state);
}
export async function cloudJobs(session: string | null) {
  if (!session) return [];
  const result = await list({ prefix: `records/${session}/`, limit: 1000 });
  const records = await Promise.all(
    result.blobs.map(
      async (b) => (await jsonBlob<CloudState>(b.pathname))?.body,
    ),
  );
  return records
    .filter((r): r is CloudState => !!r)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 20)
    .map(publicJob);
}
export async function cloudJob(
  session: string | null,
  id: string,
  ports: CloudPorts = defaultPorts,
) {
  if (!session) return null;
  const key = keyOf(session, id);
  const result = await ports.read(key);
  if (result && ["queued", "running"].includes(result.body.status)) {
    const state = result.body;
    const age = Date.now() - Date.parse(state.created_at);
    if (age >= 86400000 && (!state.lease || state.lease.until <= Date.now())) {
      const failed: CloudState = {
        ...state,
        status: "failed",
        lease: undefined,
        error: "İşlem kuyrukta süre sınırını aştı. Yeniden analiz başlatın.",
        updated_at: new Date().toISOString(),
      };
      await ports.write(key, failed, result.etag);
      return publicJob(failed);
    }
    // Admission can commit before send() fails (or its response is lost).
    // Reuse the stage's idempotency key; never admit a second expensive job.
    if (state.status === "queued" && state.attempts === 0 && age >= 30000) {
      try {
        await ports.enqueue({ id, session, stage: state.stage });
      } catch {
        console.error(
          JSON.stringify({ event: "queue_recovery_pending", job_id: id }),
        );
      }
    }
  }
  return result ? publicJob(result.body) : null;
}
export async function cloudFile(
  session: string | null,
  id: string,
  name: string,
) {
  if (!session) throw new CloudError("Sonuç bulunamadı", 404);
  const current = await jsonBlob<CloudState>(keyOf(session, id));
  const state = current?.body;
  if (!state || state.status !== "succeeded" || !state.files?.[name])
    throw new CloudError("Dosya bulunamadı", 404);
  const reference = state.files[name];
  if (!reference.path.startsWith(`analysis/${session}/${id}/`))
    throw new CloudError("Dosya sahipliği doğrulanamadı");
  if (reference.size > 4000000) {
    const validUntil = Date.now() + 120000;
    const token = await issueSignedToken({
      pathname: reference.path,
      operations: ["get"],
      validUntil,
    });
    const url = await presignUrl(token, {
      access: "private",
      operation: "get",
      pathname: reference.path,
      validUntil,
    });
    return Response.redirect(url.presignedUrl, 307);
  }
  const result = await get(reference.path, {
    access: "private",
    useCache: false,
  });
  if (!result?.stream) throw new CloudError("Dosya bulunamadı", 404);
  return new Response(result.stream, {
    headers: {
      "Content-Type": result.blob.contentType || "application/octet-stream",
      "Content-Disposition": `attachment; filename="${name}"`,
      "Cache-Control": "private, no-store",
    },
  });
}
export async function cloudInspect(
  session: string | null,
  id: string,
  request: Request,
) {
  if (!session) throw new CloudError("Sonuç bulunamadı", 404);
  const current = await jsonBlob<CloudState>(keyOf(session, id));
  const state = current?.body;
  if (!state?.report || !state.files?.["score.tif"])
    throw new CloudError("Sonuç bulunamadı", 404);
  const q = new URL(request.url).searchParams,
    lon = Number(q.get("longitude")),
    lat = Number(q.get("latitude"));
  if (
    !q.has("longitude") ||
    !q.has("latitude") ||
    !Number.isFinite(lon) ||
    !Number.isFinite(lat) ||
    Math.abs(lon) > 180 ||
    Math.abs(lat) > 90
  )
    throw new CloudError("Geçersiz koordinat", 422);
  const grid = state.report.grid,
    utm = /^EPSG:326(\d{2})$/.exec(grid.crs);
  if (!utm) throw new CloudError("Desteklenmeyen harita izdüşümü");
  const [x, y] = proj4(
    "EPSG:4326",
    `+proj=utm +zone=${Number(utm[1])} +datum=WGS84 +units=m +no_defs`,
    [lon, lat],
  );
  const [a, b, c, d, e, f] = grid.transform;
  if (b !== 0 || d !== 0)
    throw new CloudError("Desteklenmeyen harita ızgarası");
  const col = Math.floor((x - c) / a),
    row = Math.floor((y - f) / e);
  if (col < 0 || row < 0 || col >= grid.width || row >= grid.height)
    throw new CloudError("Coordinates outside analysis grid", 422);
  // Inspect large rasters privately on the server; export redirects are for
  // browser downloads and have no raster body to decode here.
  const scoreFile = await get(state.files["score.tif"].path, {
    access: "private",
    useCache: false,
  });
  if (!scoreFile?.stream) throw new CloudError("Dosya bulunamadı", 404);
  const tiff = await fromArrayBuffer(
    await new Response(scoreFile.stream).arrayBuffer(),
  );
  const raster = await tiff.getImage();
  const values = await raster.readRasters({
    window: [col, row, col + 1, row + 1],
    samples: [0],
    interleave: true,
  });
  const score = Number(values[0]);
  return Response.json({
    score:
      score === raster.getGDALNoData() || !Number.isFinite(score)
        ? null
        : score,
    meaning: "uncalibrated annual forest-loss-reference score",
    resolution_m: 30,
  });
}
export async function cloudHealth() {
  const destination = new URL("/health", process.env.ECOSENTINEL_BACKEND_URL);
  const response = await fetch(destination, {
    headers: { Authorization: `Bearer ${signingKey()}` },
    cache: "no-store",
    signal: AbortSignal.timeout(20000),
    redirect: "error",
  });
  if (!response.ok) throw new CloudError("Analiz sunucusuna bağlanılamadı");
  const health = await response.json();
  if (!health.storage_configured)
    throw new CloudError("Sonuç depolama alanı yapılandırılmadı");
  return health;
}
