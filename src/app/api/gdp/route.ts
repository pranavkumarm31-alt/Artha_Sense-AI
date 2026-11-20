import { serveDataset } from "@/lib/api-route";
import { fetchGDPData } from "@/lib/data-fetchers";
import type { GDPDataPoint } from "@/lib/types";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: NextRequest) {
  return serveDataset<GDPDataPoint[]>(request, "National Accounts Statistics", fetchGDPData, {
    frequency: "Quarterly",
  });
}
