import { NextResponse } from "next/server";

export async function GET() {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json({ error: "Research service is not configured." }, { status: 503 });
  }
  try {
    const response = await fetch(`${serviceUrl}/v1/research/sources`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Source listing failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Research API] Source listing unavailable:", error);
    return NextResponse.json(
      { error: "Research service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
