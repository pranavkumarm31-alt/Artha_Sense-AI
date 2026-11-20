import { timingSafeEqual } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

import { fetchCPIData, fetchGDPData, fetchIIPData, fetchWPIData } from "@/lib/data-fetchers";
import {
  type IngestSourceFailure,
  type IngestSourceResult,
  buildIngestionPayload,
} from "@/lib/intelligence-ingest";

function isAuthorized(request: NextRequest, token: string): boolean {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) return false;
  const provided = Buffer.from(authorization.slice("Bearer ".length).trim());
  const expected = Buffer.from(token);
  return provided.length === expected.length && timingSafeEqual(provided, expected);
}

export async function POST(request: NextRequest) {
  const token = process.env.INTELLIGENCE_API_TOKEN;
  if (!token) {
    return NextResponse.json(
      { error: "Historical ingestion is not configured on this deployment." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
  if (!isAuthorized(request, token)) {
    return NextResponse.json(
      { error: "Unauthorized." },
      { status: 401, headers: { "Cache-Control": "no-store" } }
    );
  }

  const serviceUrl = process.env.INTELLIGENCE_SERVICE_URL?.replace(/\/+$/, "");
  if (!serviceUrl) {
    return NextResponse.json(
      { error: "Historical ingestion service URL is not configured." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  const results = await Promise.allSettled([
    fetchGDPData(true).then(
      (result): IngestSourceResult => ({
        sourceKey: "nas",
        dataset: "NAS",
        ...result,
      })
    ),
    fetchCPIData(true).then(
      (result): IngestSourceResult => ({
        sourceKey: "cpi",
        dataset: "CPI",
        ...result,
      })
    ),
    fetchWPIData(true).then(
      (result): IngestSourceResult => ({
        sourceKey: "wpi",
        dataset: "WPI",
        ...result,
      })
    ),
    fetchIIPData(true).then(
      (result): IngestSourceResult => ({
        sourceKey: "iip",
        dataset: "IIP",
        ...result,
      })
    ),
  ]);
  const sources: IngestSourceResult[] = [];
  const failedSources: IngestSourceFailure[] = [];
  const sourceDetails = [
    { sourceKey: "nas", dataset: "NAS" },
    { sourceKey: "cpi", dataset: "CPI" },
    { sourceKey: "wpi", dataset: "WPI" },
    { sourceKey: "iip", dataset: "IIP" },
  ] as const;
  results.forEach((result, index) => {
    if (result.status === "fulfilled") {
      sources.push(result.value);
    } else {
      console.error(`[Intelligence ingestion] Source ${index + 1} fetch failed:`, result.reason);
      const source = sourceDetails[index];
      failedSources.push({
        sourceKey: source.sourceKey,
        dataset: source.dataset,
        error: result.reason instanceof Error ? result.reason.message : "Source fetch failed.",
      });
    }
  });

  if (sources.length === 0) {
    return NextResponse.json(
      { error: "No official datasets could be fetched for ingestion." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  let payload: ReturnType<typeof buildIngestionPayload>;
  try {
    payload = buildIngestionPayload(sources, failedSources);
  } catch (error) {
    console.error("[Intelligence ingestion] Payload validation failed:", error);
    return NextResponse.json(
      { error: "Fetched data did not contain valid observations for ingestion." },
      { status: 502, headers: { "Cache-Control": "no-store" } }
    );
  }

  try {
    const response = await fetch(`${serviceUrl}/v1/ingest`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(120_000),
      cache: "no-store",
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      console.error(
        "[Intelligence ingestion] Storage service rejected the payload:",
        response.status
      );
      return NextResponse.json(
        { error: "Historical storage service rejected ingestion.", detail: body?.detail ?? null },
        { status: 502, headers: { "Cache-Control": "no-store" } }
      );
    }

    return NextResponse.json(
      { result: body, sourceCount: sources.length },
      { headers: { "Cache-Control": "no-store" } }
    );
  } catch (error) {
    console.error("[Intelligence ingestion] Storage service unavailable:", error);
    return NextResponse.json(
      { error: "Historical storage service is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }
}
