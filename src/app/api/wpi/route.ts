import { serveDataset } from "@/lib/api-route";
import { fetchWPIData } from "@/lib/data-fetchers";
import type { WPIDataPoint } from "@/lib/types";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: NextRequest) {
  return serveDataset<WPIDataPoint[]>(request, "Wholesale Price Index", fetchWPIData, {
    baseYear: "2022-23",
    frequency: "Monthly",
    group: "Overall index",
  });
}
