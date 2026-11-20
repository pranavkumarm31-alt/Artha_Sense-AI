import { type NextRequest, NextResponse } from "next/server";
import type { APIResponse } from "./types";

type FetchResult<T> = {
  data: T;
  status: "live" | "stale";
  lastSuccessfulFetch: string;
  warning?: string;
};

const SOURCE_NAME = "Ministry of Statistics and Programme Implementation (MoSPI)";

export async function serveDataset<T>(
  request: NextRequest,
  dataset: string,
  fetcher: (force: boolean) => Promise<FetchResult<T>>,
  metadata?: Record<string, string>
) {
  try {
    const force = request.nextUrl.searchParams.get("refresh") === "true";
    const result = await fetcher(force);
    const response: APIResponse<T> = {
      data: result.data,
      status: result.status === "live" ? "LIVE" : "STALE",
      lastSuccessfulFetch: result.lastSuccessfulFetch,
      source: `${SOURCE_NAME} — ${dataset}`,
      ...(result.warning ? { error: result.warning } : {}),
      ...(metadata ? { metadata } : {}),
    };

    return NextResponse.json(response, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error(`[MoSPI] ${dataset} API unavailable:`, error);
    const response: APIResponse<T> = {
      data: null,
      status: "OFFLINE",
      lastSuccessfulFetch: null,
      source: `${SOURCE_NAME} — ${dataset}`,
      error: "Official source unavailable and no cached observations are available.",
      ...(metadata ? { metadata } : {}),
    };

    return NextResponse.json(response, {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }
}
