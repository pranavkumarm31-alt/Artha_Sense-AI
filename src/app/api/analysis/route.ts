import { type NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json(
      { error: "Economic analysis service is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  const view = request.nextUrl.searchParams.get("view") ?? "trends";
  const indicator = request.nextUrl.searchParams.get("indicator");
  const start = request.nextUrl.searchParams.get("start");
  const end = request.nextUrl.searchParams.get("end");
  const window = request.nextUrl.searchParams.get("window");

  let path: string;
  if (view === "correlations") {
    path = "/v1/analysis/correlations";
  } else if (view === "insights") {
    path = "/v1/analysis/insights";
  } else if (view === "sectors") {
    path = "/v1/analysis/sectors";
  } else if (!indicator) {
    return NextResponse.json(
      { error: "indicator is required." },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  } else if (view === "growth") {
    path = `/v1/analysis/growth/${indicator}`;
  } else if (view === "volatility") {
    path = `/v1/analysis/volatility/${indicator}`;
  } else {
    path = `/v1/analysis/trends/${indicator}`;
  }

  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (window) params.set("window", window);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";

  try {
    const response = await fetch(`${serviceUrl}${path}${suffix}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(60_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Economic analysis failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Economic Analysis API] Query unavailable:", error);
    return NextResponse.json(
      { error: "Economic analysis service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
