import { type NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json(
      { error: "Forecasting service is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const body = await request.json();
    const response = await fetch(`${serviceUrl}/v1/forecasts/generate`, {
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
    if (!response.ok) {
      return NextResponse.json(
        { error: payload?.detail ?? "Forecast generation failed." },
        { status: response.status, headers: { "Cache-Control": "no-store" } }
      );
    }
    return NextResponse.json(payload, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("[Forecast API] Generation unavailable:", error);
    return NextResponse.json(
      { error: "Forecasting service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}

export async function GET(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json(
      { error: "Forecasting service is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  const indicator = request.nextUrl.searchParams.get("indicator");
  const view = request.nextUrl.searchParams.get("view") ?? "saved";
  const model = request.nextUrl.searchParams.get("model");
  if (!indicator) {
    return NextResponse.json(
      { error: "indicator is required." },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }

  const baseUrl = `${serviceUrl}/v1/forecasts/${indicator}`;
  const requestUrl =
    view === "compare"
      ? `${baseUrl}/compare`
      : view === "history"
        ? `${baseUrl}/history-versus-forecast?model=${encodeURIComponent(model ?? "naive")}`
        : `${baseUrl}${model ? `?model=${encodeURIComponent(model)}&limit=100` : "?limit=100"}`;

  try {
    const response = await fetch(requestUrl, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(30_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    return NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Forecast query failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Forecast API] Query unavailable:", error);
    return NextResponse.json(
      { error: "Forecasting service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
