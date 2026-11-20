import { serveDataset } from "@/lib/api-route";
import { fetchIIPData } from "@/lib/data-fetchers";
import type { IIPDataPoint } from "@/lib/types";
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: NextRequest) {
  return serveDataset<IIPDataPoint[]>(request, "Index of Industrial Production", fetchIIPData, {
    baseYear: "2011-12",
    frequency: "Monthly",
  });
}
