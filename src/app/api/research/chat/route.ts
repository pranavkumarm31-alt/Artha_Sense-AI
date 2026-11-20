import { randomUUID } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "arthasense_research_session";

export async function POST(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!token || !serviceUrl) {
    return NextResponse.json({ error: "Research service is not configured." }, { status: 503 });
  }

  const ownerId = request.cookies.get(SESSION_COOKIE)?.value ?? randomUUID();
  try {
    const body = await request.json();
    const response = await fetch(`${serviceUrl}/v1/research/chat`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Research-Owner": ownerId,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(90_000),
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    const result = NextResponse.json(
      response.ok ? payload : { error: payload?.detail ?? "Research request failed." },
      { status: response.status, headers: { "Cache-Control": "no-store" } }
    );
    if (response.ok && !request.cookies.has(SESSION_COOKIE)) {
      result.cookies.set(SESSION_COOKIE, ownerId, {
        httpOnly: true,
        sameSite: "strict",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: 60 * 60 * 24 * 30,
      });
    }
    return result;
  } catch (error) {
    console.error("[Research API] Chat unavailable:", error);
    return NextResponse.json(
      { error: "Research service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
