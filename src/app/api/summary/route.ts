import { serveDataset } from "@/lib/api-route";
import { fetchSummaryStats } from "@/lib/data-fetchers";
import type { SummaryStats } from "@/lib/types";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: NextRequest) {
  return serveDataset<SummaryStats>(request, "Economic Summary Statistics", fetchSummaryStats);
}
