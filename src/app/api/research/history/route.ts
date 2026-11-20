import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "arthasense_research_session";

export async function GET(request: NextRequest) {
  const ownerId = request.cookies.get(SESSION_COOKIE)?.value;
  if (!ownerId) return NextResponse.json([], { headers: { "Cache-Control": "no-store" } });

  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json({ error: "Research service is not configured." }, { status: 503 });
  }
  try {
    const response = await fetch(`${serviceUrl}/v1/research/history`, {
      headers: { Authorization: `Bearer ${token}`, "X-Research-Owner": ownerId },
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Research history failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Research API] History unavailable:", error);
    return NextResponse.json(
      { error: "Research service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
