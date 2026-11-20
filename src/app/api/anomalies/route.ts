import { type NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json(
      { error: "Anomaly detection service is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
  try {
    const body = await request.json();
    const response = await fetch(`${serviceUrl}/v1/anomalies/detect`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(300_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Anomaly detection failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Anomaly API] Detection unavailable:", error);
    return NextResponse.json(
      { error: "Anomaly detection service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}

export async function GET(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json(
      { error: "Anomaly detection service is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  const view = request.nextUrl.searchParams.get("view") ?? "list";
  const indicator = request.nextUrl.searchParams.get("indicator");
  const severity = request.nextUrl.searchParams.get("severity");
  const method = request.nextUrl.searchParams.get("method");
  const start = request.nextUrl.searchParams.get("start");
  const end = request.nextUrl.searchParams.get("end");

  let path = "/v1/anomalies";
  if (view === "summary") path = "/v1/anomalies/summary";
  else if (view === "methods") path = "/v1/anomalies/methods";
  else if (indicator) path = `/v1/anomalies/${indicator}`;

  const params = new URLSearchParams();
  if (severity) params.set("severity", severity);
  if (method) params.set("method", method);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";

  try {
    const response = await fetch(`${serviceUrl}${path}${suffix}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(60_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Anomaly query failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Anomaly API] Query unavailable:", error);
    return NextResponse.json(
      { error: "Anomaly detection service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
