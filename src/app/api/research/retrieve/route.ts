import { type NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json({ error: "Research service is not configured." }, { status: 503 });
  }
  try {
    const body = await request.json();
    const response = await fetch(`${serviceUrl}/v1/research/retrieve`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(45_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Research retrieval failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Research API] Retrieval unavailable:", error);
    return NextResponse.json(
      { error: "Research service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
