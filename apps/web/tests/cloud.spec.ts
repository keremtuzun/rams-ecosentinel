import { expect, test } from "@playwright/test";
import {
  CloudError,
  getSession,
  processCloudStage,
  cloudJob,
  reserveQuota,
  type CloudState,
  type CloudPorts,
  type StageMessage,
} from "../lib/cloud-analysis";
// In-memory coordination fixtures only. No synthetic artifact is published as a result.
function fixture() {
  let state: CloudState = {
    id: "11111111-1111-4111-8111-111111111111",
    session: "a".repeat(32),
    stage: "before",
    stage_attempts: 0,
    observations: {},
    status: "queued",
    request: {},
    attempts: 0,
    error: null,
    created_at: "2026-10-14T00:00:00Z",
    updated_at: "2026-10-14T00:00:00Z",
  };
  let revision = 0;
  let calls = 0;
  const sent: StageMessage[] = [];
  const ports: CloudPorts = {
    read: async () => ({
      body: structuredClone(state),
      etag: String(revision),
    }),
    write: async (_key, next, etag) => {
      if (etag !== String(revision)) throw new Error("CAS conflict");
      state = structuredClone(next);
      revision++;
      return String(revision);
    },
    rpc: async (body) => {
      calls++;
      const r = body as { session: string; id: string; owner: string };
      const prefix = `analysis/${r.session}/${r.id}/${r.owner}`;
      return {
        data: {
          path: prefix + "/observation.npz",
          sha256: "0".repeat(64),
          size: 1,
        },
        metadata: {
          path: prefix + "/observation.json",
          sha256: "0".repeat(64),
          size: 1,
        },
      };
    },
    enqueue: async (message) => {
      sent.push(message);
    },
  };
  return {
    ports,
    message: {
      id: state.id,
      session: state.session,
      stage: "before",
    } as StageMessage,
    get state() {
      return state;
    },
    get calls() {
      return calls;
    },
    sent,
    replace(next: CloudState) {
      state = next;
      revision++;
    },
  };
}
test("duplicate delivery repairs dispatch without computing twice", async () => {
  const f = fixture();
  await processCloudStage(f.message, f.ports);
  expect(f.state.stage).toBe("after");
  await processCloudStage(f.message, f.ports);
  expect(f.calls).toBe(1);
  expect(f.sent.map((x) => x.stage)).toEqual(["after", "after"]);
});

test("a queued record survives lost admission dispatch and is re-enqueued without a new job", async () => {
  const f = fixture();
  f.replace({
    ...f.state,
    created_at: new Date(Date.now() - 60000).toISOString(),
  });
  const record = await cloudJob(f.message.session, f.message.id, f.ports);
  expect(record?.id).toBe(f.message.id);
  expect(f.sent).toEqual([f.message]);
  expect(f.calls).toBe(0);
});

test("expired undelivered jobs fail explicitly after queue retention", async () => {
  const f = fixture();
  f.replace({
    ...f.state,
    created_at: new Date(Date.now() - 86400001).toISOString(),
  });
  expect(
    (await cloudJob(f.message.session, f.message.id, f.ports))?.status,
  ).toBe("failed");
  expect(f.sent).toEqual([]);
  expect(f.calls).toBe(0);
});

test("temporary compute failures retry only after lease expiry, with a two-attempt bound", async () => {
  const f = fixture();
  f.ports.rpc = async () => {
    throw new CloudError("temporary network outage", 503);
  };
  await expect(processCloudStage(f.message, f.ports)).rejects.toThrow(
    "network outage",
  );
  await expect(processCloudStage(f.message, f.ports)).rejects.toThrow("leased");
  expect(f.state.stage_attempts).toBe(1);
  f.replace({ ...f.state, lease: { owner: "expired", until: 0 } });
  await expect(processCloudStage(f.message, f.ports)).rejects.toThrow(
    "network outage",
  );
  f.replace({ ...f.state, lease: { owner: "expired", until: 0 } });
  await processCloudStage(f.message, f.ports);
  expect(f.state.status).toBe("failed");
  expect(f.state.stage_attempts).toBe(2);
  expect(f.state.report).toBeUndefined();
});

test("quota admission preserves session/global bounds and idempotency under conflicts", async () => {
  let quota: { ids: string[]; sessions: Record<string, number> } | null = null;
  let revision = 0;
  const ports = {
    read: async () =>
      quota ? { body: structuredClone(quota), etag: String(revision) } : null,
    write: async (
      _key: string,
      body: NonNullable<typeof quota>,
      etag?: string,
    ) => {
      if (etag !== (quota ? String(revision) : undefined))
        throw new Error("already exists");
      quota = structuredClone(body);
      return String(++revision);
    },
  };
  await reserveQuota("one", "session-a", ports);
  await reserveQuota("one", "session-a", ports);
  await reserveQuota("two", "session-a", ports);
  await reserveQuota("three", "session-a", ports);
  await expect(reserveQuota("four", "session-a", ports)).rejects.toMatchObject({
    status: 429,
  });
  await Promise.all([
    reserveQuota("five", "session-b", ports),
    reserveQuota("six", "session-c", ports),
  ]);
  for (const id of ["seven", "eight", "nine"])
    await reserveQuota(id, id, ports);
  await expect(reserveQuota("ten", "session-d", ports)).rejects.toMatchObject({
    status: 429,
  });
  expect(quota!.ids).toHaveLength(8);
  expect(quota!.sessions["session-a"]).toBe(3);
});
test("committed progress survives a failed next-stage publish", async () => {
  const f = fixture();
  f.ports.enqueue = async () => {
    throw new Error("accepted then timeout unknown");
  };
  await expect(processCloudStage(f.message, f.ports)).rejects.toThrow();
  expect(f.state.stage).toBe("after");
  f.ports.enqueue = async (message) => {
    f.sent.push(message);
  };
  await processCloudStage(f.message, f.ports);
  expect(f.calls).toBe(1);
  expect(f.sent[0].stage).toBe("after");
});
test("late owner cannot overwrite a newer terminal state", async () => {
  const f = fixture();
  const rpc = f.ports.rpc;
  f.ports.rpc = async (body) => {
    const result = await rpc(body);
    f.replace({ ...f.state, status: "failed", error: "owner revoked" });
    return result;
  };
  await expect(processCloudStage(f.message, f.ports)).rejects.toThrow(
    "CAS conflict",
  );
  expect(f.state.status).toBe("failed");
  expect(f.state.error).toBe("owner revoked");
});
test("data failures end explicitly and never become completed results", async () => {
  const f = fixture();
  f.ports.rpc = async () => {
    throw new CloudError("Insufficient jointly clear observations", 422);
  };
  await processCloudStage(f.message, f.ports);
  expect(f.state.status).toBe("failed");
  expect(f.state.report).toBeUndefined();
  expect(f.sent).toEqual([]);
});
test("future delivery cannot be acknowledged before its predecessor", async () => {
  const f = fixture();
  await expect(
    processCloudStage({ ...f.message, stage: "infer" }, f.ports),
  ).rejects.toThrow("not ready");
  expect(f.calls).toBe(0);
  expect(f.state.status).toBe("queued");
});
test("session signatures reject forged and missing ownership", async () => {
  const previous = process.env.ECOSENTINEL_BACKEND_TOKEN;
  process.env.ECOSENTINEL_BACKEND_TOKEN = "test-fixture-key-only";
  try {
    const created = getSession(new Request("http://localhost/health"), true);
    const cookie = created.cookie!.split(";")[0];
    expect(
      getSession(
        new Request("http://localhost/api/jobs", { headers: { cookie } }),
      ).id,
    ).toBe(created.id);
    expect(
      getSession(
        new Request("http://localhost/api/jobs", {
          headers: { cookie: cookie + "forged" },
        }),
      ).id,
    ).toBeNull();
    expect(getSession(new Request("http://localhost/api/jobs")).id).toBeNull();
  } finally {
    if (previous === undefined) delete process.env.ECOSENTINEL_BACKEND_TOKEN;
    else process.env.ECOSENTINEL_BACKEND_TOKEN = previous;
  }
});
