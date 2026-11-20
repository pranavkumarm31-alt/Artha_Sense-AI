import { getMonthIndex } from "./date-utils";
import type { CPIDataPoint, GDPDataPoint, IIPDataPoint, WPIDataPoint } from "./types";

export type IngestSourceResult =
  | {
      sourceKey: "nas";
      dataset: "NAS";
      data: GDPDataPoint[];
      status: "live" | "stale";
      lastSuccessfulFetch: string;
    }
  | {
      sourceKey: "cpi";
      dataset: "CPI";
      data: CPIDataPoint[];
      status: "live" | "stale";
      lastSuccessfulFetch: string;
    }
  | {
      sourceKey: "wpi";
      dataset: "WPI";
      data: WPIDataPoint[];
      status: "live" | "stale";
      lastSuccessfulFetch: string;
    }
  | {
      sourceKey: "iip";
      dataset: "IIP";
      data: IIPDataPoint[];
      status: "live" | "stale";
      lastSuccessfulFetch: string;
    };

export interface IngestSourceFailure {
  sourceKey: "nas" | "cpi" | "wpi" | "iip";
  dataset: "NAS" | "CPI" | "WPI" | "IIP";
  error: string;
}

interface Observation {
  source_key: string;
  metric_code: string;
  name: string;
  frequency: "monthly" | "quarterly";
  observation_period: string;
  observation_start: string;
  fiscal_year: string;
  quarter?: string;
  month?: number;
  value: number;
  value_type: "official" | "calculated";
  unit: string;
  base_year: string;
  source_status: "LIVE" | "STALE";
  last_fetched_at: string;
  publication_date: null;
  source_metadata: Record<string, unknown>;
}

function monthStart(year: string, month: string): string {
  const monthNumber = getMonthIndex(month) + 1;
  if (!/^\d{4}$/.test(year) || monthNumber < 1 || monthNumber > 12) {
    throw new Error(`Invalid monthly observation period: ${month} ${year}`);
  }
  return `${year}-${String(monthNumber).padStart(2, "0")}-01`;
}

function quarterStart(year: string, quarter: string): string {
  const startYear = Number(year.slice(0, 4));
  const quarterNumber = Number(quarter.slice(1));
  if (
    !/^\d{4}-\d{2}$/.test(year) ||
    !Number.isInteger(quarterNumber) ||
    quarterNumber < 1 ||
    quarterNumber > 4
  ) {
    throw new Error(`Invalid quarterly observation period: ${quarter} FY ${year}`);
  }
  const zeroBasedMonth = 3 + (quarterNumber - 1) * 3;
  const calendarYear = startYear + Math.floor(zeroBasedMonth / 12);
  const month = (zeroBasedMonth % 12) + 1;
  return `${calendarYear}-${String(month).padStart(2, "0")}-01`;
}

function makeObservation(
  source: IngestSourceResult,
  period: {
    label: string;
    start: string;
    fiscalYear: string;
    quarter?: string;
    month?: number;
  },
  metric: {
    code: string;
    name: string;
    value: number | null;
    valueType: "official" | "calculated";
    unit: string;
    baseYear: string;
    metadata?: Record<string, unknown>;
  },
  frequency: "monthly" | "quarterly"
): Observation | null {
  if (metric.value === null || !Number.isFinite(metric.value)) return null;

  return {
    source_key: source.sourceKey,
    metric_code: metric.code,
    name: metric.name,
    frequency,
    observation_period: period.label,
    observation_start: period.start,
    fiscal_year: period.fiscalYear,
    ...(period.quarter ? { quarter: period.quarter } : {}),
    ...(period.month ? { month: period.month } : {}),
    value: metric.value,
    value_type: metric.valueType,
    unit: metric.unit,
    base_year: metric.baseYear,
    source_status: source.status === "live" ? "LIVE" : "STALE",
    last_fetched_at: source.lastSuccessfulFetch,
    publication_date: null,
    source_metadata: metric.metadata ?? {},
  };
}

export function buildIngestionPayload(
  sources: IngestSourceResult[],
  failedSources: IngestSourceFailure[] = []
) {
  const observations: Observation[] = [];

  for (const source of sources) {
    switch (source.sourceKey) {
      case "nas":
        for (const point of source.data) {
          const period = {
            label: point.period,
            start: quarterStart(point.year, point.quarter),
            fiscalYear: point.year,
            quarter: point.quarter,
          };
          const common = {
            fiscalYear: point.year,
            quarter: point.quarter,
            estimateStatus: point.estimateStatus,
          };
          const metrics = [
            {
              code: "gdp_real_growth",
              name: "Real GDP growth",
              value: point.gdpGrowth,
              valueType: "official" as const,
              unit: "%",
              baseYear: "2011-12",
            },
            {
              code: "gdp_nominal",
              name: "Nominal GDP",
              value: point.gdpNominal,
              valueType: "official" as const,
              unit: "lakh crore INR",
              baseYear: "2011-12",
            },
            {
              code: "gva_agriculture_growth",
              name: "GVA Agriculture growth",
              value: point.gvaAgriculture,
              valueType: "official" as const,
              unit: "%",
              baseYear: "2011-12",
            },
            {
              code: "gva_industry_growth",
              name: "GVA Industry growth",
              value: point.gvaIndustry,
              valueType: "calculated" as const,
              unit: "%",
              baseYear: "2011-12",
              metadata: { calculation: "growth from official constant-price GVA levels" },
            },
            {
              code: "gva_services_growth",
              name: "GVA Services growth",
              value: point.gvaServices,
              valueType: "calculated" as const,
              unit: "%",
              baseYear: "2011-12",
              metadata: { calculation: "growth from official constant-price GVA levels" },
            },
          ];
          observations.push(
            ...metrics
              .map((metric) =>
                makeObservation(
                  source,
                  period,
                  { ...metric, metadata: { ...common, ...metric.metadata } },
                  "quarterly"
                )
              )
              .filter((value): value is Observation => value !== null)
          );
        }
        break;
      case "cpi":
        for (const point of source.data) {
          const period = {
            label: point.period,
            start: monthStart(point.year, point.month),
            fiscalYear: point.fiscalYear,
            month: getMonthIndex(point.month) + 1,
          };
          const metrics = [
            {
              code: "cpi_general_index",
              name: "CPI General index",
              value: point.cpiGeneral,
              valueType: "official" as const,
              unit: "index",
              baseYear: "2024",
            },
            {
              code: "cpi_inflation",
              name: "CPI inflation",
              value: point.inflationRate,
              valueType:
                point.inflationSource === "calculated"
                  ? ("calculated" as const)
                  : ("official" as const),
              unit: "%",
              baseYear: "2024",
              metadata: { source: point.inflationSource },
            },
          ];
          observations.push(
            ...metrics
              .map((metric) => makeObservation(source, period, metric, "monthly"))
              .filter((value): value is Observation => value !== null)
          );
        }
        break;
      case "wpi":
        for (const point of source.data) {
          const period = {
            label: point.period,
            start: monthStart(point.year, point.month),
            fiscalYear: point.fiscalYear,
            month: getMonthIndex(point.month) + 1,
          };
          const metrics = [
            {
              code: "wpi_overall_index",
              name: "WPI Overall index",
              value: point.wpiAll,
              valueType: "official" as const,
              unit: "index",
              baseYear: "2022-23",
            },
            {
              code: "wpi_inflation",
              name: "WPI inflation",
              value: point.wpiInflation,
              valueType: "calculated" as const,
              unit: "%",
              baseYear: "2022-23",
              metadata: { calculation: "same calendar month in prior year" },
            },
          ];
          observations.push(
            ...metrics
              .map((metric) => makeObservation(source, period, metric, "monthly"))
              .filter((value): value is Observation => value !== null)
          );
        }
        break;
      case "iip":
        for (const point of source.data) {
          const period = {
            label: point.period,
            start: monthStart(point.year, point.month),
            fiscalYear: point.fiscalYear,
            month: getMonthIndex(point.month) + 1,
          };
          const metrics: Array<{
            code: string;
            name: string;
            value: number | null;
            unit: string;
          }> = [
            {
              code: "iip_general_index",
              name: "IIP General index",
              value: point.iipGeneral,
              unit: "index",
            },
            {
              code: "iip_mining_index",
              name: "IIP Mining index",
              value: point.iipMining,
              unit: "index",
            },
            {
              code: "iip_manufacturing_index",
              name: "IIP Manufacturing index",
              value: point.iipManufacturing,
              unit: "index",
            },
            {
              code: "iip_electricity_index",
              name: "IIP Electricity index",
              value: point.iipElectricity,
              unit: "index",
            },
            { code: "iip_growth", name: "IIP growth", value: point.growthRate, unit: "%" },
          ].map((metric) => ({
            ...metric,
            valueType: "official" as const,
            baseYear: "2011-12",
          }));
          observations.push(
            ...metrics
              .map((metric) =>
                makeObservation(
                  source,
                  period,
                  { ...metric, valueType: "official", baseYear: "2011-12" },
                  "monthly"
                )
              )
              .filter((value): value is Observation => value !== null)
          );
        }
        break;
    }
  }

  if (observations.length === 0) {
    throw new Error("No numeric official observations were available to archive.");
  }

  const uniqueObservations = [
    ...new Map(
      observations.map((observation) => [
        `${observation.source_key}:${observation.metric_code}:${observation.observation_period}`,
        observation,
      ])
    ).values(),
  ].sort(
    (first, second) =>
      first.source_key.localeCompare(second.source_key) ||
      first.metric_code.localeCompare(second.metric_code) ||
      first.observation_start.localeCompare(second.observation_start)
  );

  return {
    source_name: "Ministry of Statistics and Programme Implementation (MoSPI)",
    source_url: "https://mcp.mospi.gov.in/",
    fetches: sources.map((source) => ({
      source_key: source.sourceKey,
      dataset: source.dataset,
      status: source.status === "live" ? "LIVE" : "STALE",
      last_successful_fetch: source.lastSuccessfulFetch,
      observation_count: source.data.length,
    })),
    failed_sources: failedSources.map((source) => ({
      source_key: source.sourceKey,
      dataset: source.dataset,
      error: source.error.slice(0, 500),
    })),
    observations: uniqueObservations,
  };
}
