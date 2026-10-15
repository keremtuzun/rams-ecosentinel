import { handleHostedApi } from "../../lib/hosted-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  return handleHostedApi(request, "/health");
}
