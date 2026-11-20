import { formatMonthlyObservationWithFiscalYear } from "./date-utils";
import type { CPIDataPoint, GDPDataPoint, IIPDataPoint, SummaryStats, WPIDataPoint } from "./types";

function computeTrend(values: Array<number | null | undefined>): "up" | "down" | "stable" {
  const validValues = values.filter(
    (value): value is number => value !== null && value !== undefined && Number.isFinite(value)
  );
  if (validValues.length < 2) return "stable";

  const last = validValues[validValues.length - 1];
  const previous = validValues[validValues.length - 2];
  if (last > previous + 0.01) return "up";
  if (last < previous - 0.01) return "down";
  return "stable";
}

function getLatestAvailable<T>(
  rows: T[],
  getValue: (row: T) => number | null | undefined
): T | undefined {
  return [...rows].reverse().find((row) => {
    const value = getValue(row);
    return value !== null && value !== undefined && Number.isFinite(value);
  });
}

export function buildSummaryStats(
  gdpData: GDPDataPoint[],
  cpiData: CPIDataPoint[],
  wpiData: WPIDataPoint[],
  iipData: IIPDataPoint[]
): SummaryStats {
  const lastGDP = getLatestAvailable(gdpData, (row) => row.gdpGrowth);
  const lastCPI = getLatestAvailable(cpiData, (row) => row.inflationRate);
  const lastWPI = getLatestAvailable(wpiData, (row) => row.wpiInflation);
  const lastIIP = getLatestAvailable(iipData, (row) => row.growthRate);

  return {
    gdpGrowth: {
      value: lastGDP?.gdpGrowth ?? null,
      quarter: lastGDP?.period ?? "N/A",
      trend: computeTrend(gdpData.map((row) => row.gdpGrowth)),
    },
    cpiInflation: {
      value: lastCPI?.inflationRate ?? null,
      month: lastCPI
        ? formatMonthlyObservationWithFiscalYear(lastCPI.month, lastCPI.year, lastCPI.fiscalYear)
        : "N/A",
      trend: computeTrend(cpiData.map((row) => row.inflationRate)),
    },
    wpiInflation: {
      value: lastWPI?.wpiInflation ?? null,
      month: lastWPI
        ? formatMonthlyObservationWithFiscalYear(lastWPI.month, lastWPI.year, lastWPI.fiscalYear)
        : "N/A",
      trend: computeTrend(wpiData.map((row) => row.wpiInflation)),
    },
    iipGrowth: {
      value: lastIIP?.growthRate ?? null,
      month: lastIIP
        ? formatMonthlyObservationWithFiscalYear(lastIIP.month, lastIIP.year, lastIIP.fiscalYear)
        : "N/A",
      trend: computeTrend(iipData.map((row) => row.growthRate)),
    },
  };
}
