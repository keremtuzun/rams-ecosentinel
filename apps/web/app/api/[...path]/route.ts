import { handleHostedApi } from "../../../lib/hosted-api";

export const runtime = "nodejs";
export const maxDuration = 60;

type Context = { params: Promise<{ path: string[] }> };
export async function GET(request: Request, context: Context) {
  return handleHostedApi(
    request,
    "/api/" + (await context.params).path.join("/"),
  );
}
export async function POST(request: Request, context: Context) {
  return handleHostedApi(
    request,
    "/api/" + (await context.params).path.join("/"),
  );
}
