import { serveDataset } from "@/lib/api-route";
import { fetchCPIData } from "@/lib/data-fetchers";
import type { CPIDataPoint } from "@/lib/types";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: NextRequest) {
  return serveDataset<CPIDataPoint[]>(request, "Consumer Price Index", fetchCPIData, {
    baseYear: "2024",
    frequency: "Monthly",
    series: "Current, All India, Combined, General",
  });
}
