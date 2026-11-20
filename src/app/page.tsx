"use client";

import { AnomalyDashboard } from "@/components/anomaly-dashboard";
import { CPIChart, GDPChart, IIPChart, WPIChart } from "@/components/charts";
import { EconomicAnalysisDashboard } from "@/components/economic-analysis-dashboard";
import { ForecastDashboard } from "@/components/forecast-dashboard";
import { Header, type TabId } from "@/components/header";
import { ResearchAssistant } from "@/components/research-assistant";
import { ChartSkeleton, DashboardSkeleton } from "@/components/skeletons";
import { SummaryCards } from "@/components/summary-cards";
import {
  formatFiscalQuarter,
  formatMonthlyObservation,
  getFiscalYear,
  getMonthIndex,
  isFiscalQuarter,
  isFiscalYear,
} from "@/lib/date-utils";
import { buildSummaryStats } from "@/lib/summary-stats";
import type {
  APIResponse,
  CPIDataPoint,
  DatasetStatus,
  GDPDataPoint,
  IIPDataPoint,
  SummaryStats,
  WPIDataPoint,
} from "@/lib/types";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

const sectionDescriptions: Record<TabId, { title: string; subtitle: string }> = {
  overview: {
    title: "Key Economic Indicators",
    subtitle: "Official MoSPI observations published periodically (monthly or quarterly)",
  },
  gdp: {
    title: "Gross Domestic Product",
    subtitle: "Quarterly GDP growth rate and sectoral Gross Value Added breakdown",
  },
  cpi: {
    title: "Consumer Price Index",
    subtitle: "Monthly CPI inflation tracking with RBI target band analysis",
  },
  wpi: {
    title: "Wholesale Price Index",
    subtitle: "Monthly overall WPI index and year-on-year inflation",
  },
  iip: {
    title: "Industrial Production",
    subtitle: "Monthly IIP growth rate with sectoral breakdown and radar analysis",
  },
  forecasts: {
    title: "AI Economic Forecasting",
    subtitle:
      "Validated statistical and machine-learning forecasts from persisted MoSPI observations",
  },
  analysis: {
    title: "Economic Trend Analysis",
    subtitle:
      "Data-grounded growth, volatility, correlation and sector intelligence from persisted MoSPI observations",
  },
  anomalies: {
    title: "Economic Anomaly Detection",
    subtitle: "Statistical unusual-movement detection from persisted official observations",
  },
  research: {
    title: "AI Economic Research Assistant",
    subtitle:
      "Evidence-grounded research using persisted observations, saved analysis and official publications",
  },
};

interface DashboardData {
  gdp: GDPDataPoint[] | null;
  cpi: CPIDataPoint[] | null;
  wpi: WPIDataPoint[] | null;
  iip: IIPDataPoint[] | null;
  summary: SummaryStats | null;
}

type DashboardDataset = keyof DashboardData;
type IndicatorDataset = Exclude<DashboardDataset, "summary">;

interface DatasetFetch<T> {
  data: T | null;
  status: DatasetStatus;
  lastSuccessfulFetch: string | null;
  error?: string;
}

interface StoredDashboard {
  data: DashboardData;
  lastSuccessfulFetches: Partial<Record<IndicatorDataset, string>>;
  refreshIntervalMinutes: number;
}

const STORAGE_KEY = "artha-sense-mospi-dashboard-v3";
const REFRESH_INTERVALS = [15, 60, 360];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNumberOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isDatasetPayload(key: "gdp", value: unknown): value is GDPDataPoint[];
function isDatasetPayload(key: "cpi", value: unknown): value is CPIDataPoint[];
function isDatasetPayload(key: "wpi", value: unknown): value is WPIDataPoint[];
function isDatasetPayload(key: "iip", value: unknown): value is IIPDataPoint[];
function isDatasetPayload(key: "summary", value: unknown): value is SummaryStats;
function isDatasetPayload(key: DashboardDataset, value: unknown): boolean;
function isDatasetPayload(key: DashboardDataset, value: unknown): boolean {
  if (key === "summary") {
    if (!isRecord(value)) return false;
    return ["gdpGrowth", "cpiInflation", "wpiInflation", "iipGrowth"].every((indicator) => {
      const item = value[indicator];
      return (
        isRecord(item) &&
        isNumberOrNull(item.value) &&
        typeof item.trend === "string" &&
        typeof (item.quarter ?? item.month) === "string"
      );
    });
  }

  if (!Array.isArray(value)) return false;
  const requiredPeriodKey = key === "gdp" ? "quarter" : "month";
  const valueKeys: Record<Exclude<DashboardDataset, "summary">, string[]> = {
    gdp: ["gdpGrowth", "gvaAgriculture", "gvaIndustry", "gvaServices", "gdpNominal"],
    cpi: ["cpiGeneral", "inflationRate"],
    wpi: ["wpiAll", "wpiInflation"],
    iip: ["iipGeneral", "growthRate"],
  };

  return value.every((row) => {
    if (
      !isRecord(row) ||
      typeof row[requiredPeriodKey] !== "string" ||
      typeof row.year !== "string" ||
      typeof row.period !== "string" ||
      (key !== "gdp" &&
        (typeof row.month !== "string" ||
          !/^\d{4}$/.test(row.year) ||
          getMonthIndex(row.month) < 0 ||
          typeof row.fiscalYear !== "string" ||
          getFiscalYear(row.year, row.month) !== row.fiscalYear ||
          formatMonthlyObservation(row.month, row.year) !== row.period)) ||
      (key === "gdp" &&
        (!isFiscalYear(row.year) ||
          !isFiscalQuarter(String(row.quarter)) ||
          formatFiscalQuarter(String(row.quarter), row.year) !== row.period ||
          (row.estimateStatus !== null && typeof row.estimateStatus !== "string"))) ||
      (key === "cpi" &&
        row.inflationSource !== "official" &&
        row.inflationSource !== "calculated" &&
        row.inflationSource !== null) ||
      (key === "wpi" &&
        row.wpiInflationSource !== "calculated" &&
        row.wpiInflationSource !== null) ||
      !valueKeys[key].every((field) => isNumberOrNull(row[field]))
    ) {
      return false;
    }

    return true;
  });
}

function offlineResult<T>(): DatasetFetch<T> {
  return {
    data: null,
    status: "OFFLINE",
    lastSuccessfulFetch: null,
    error: "Request failed; showing the latest saved observations when available.",
  };
}

async function fetchDataset<T>(
  endpoint: string,
  key: DashboardDataset,
  refresh: boolean
): Promise<DatasetFetch<T>> {
  try {
    const url = refresh ? `${endpoint}?refresh=true` : endpoint;
    const res = await fetch(url, { cache: "no-store" });
    const json: APIResponse<T> = await res.json();
    if (
      !isRecord(json) ||
      !["LIVE", "STALE", "UPDATING", "OFFLINE"].includes(String(json.status)) ||
      (json.data !== null && !isDatasetPayload(key, json.data))
    ) {
      console.error(`Invalid ${key.toUpperCase()} API response schema.`);
      return {
        ...offlineResult<T>(),
        error: `Invalid ${key.toUpperCase()} API response schema.`,
      };
    }

    return {
      data: json.data ?? null,
      status: json.status,
      lastSuccessfulFetch:
        typeof json.lastSuccessfulFetch === "string" ? json.lastSuccessfulFetch : null,
      ...(typeof json.error === "string" ? { error: json.error } : {}),
    };
  } catch (error) {
    console.warn(`${key.toUpperCase()} request failed:`, error);
    return offlineResult<T>();
  }
}

function getStoredDashboard(): StoredDashboard | null {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (!isRecord(stored) || !isRecord(stored.data)) return null;
    const storedData = stored.data;

    const keys: DashboardDataset[] = ["gdp", "cpi", "wpi", "iip", "summary"];
    const indicatorKeys: IndicatorDataset[] = ["gdp", "cpi", "wpi", "iip"];
    const data: DashboardData = {
      gdp: isDatasetPayload("gdp", storedData.gdp) ? storedData.gdp : null,
      cpi: isDatasetPayload("cpi", storedData.cpi) ? storedData.cpi : null,
      wpi: isDatasetPayload("wpi", storedData.wpi) ? storedData.wpi : null,
      iip: isDatasetPayload("iip", storedData.iip) ? storedData.iip : null,
      summary: isDatasetPayload("summary", storedData.summary) ? storedData.summary : null,
    };
    const lastSuccessfulFetches = isRecord(stored.lastSuccessfulFetches)
      ? Object.fromEntries(
          Object.entries(stored.lastSuccessfulFetches).filter(
            ([key, value]) =>
              indicatorKeys.includes(key as IndicatorDataset) && typeof value === "string"
          )
        )
      : {};
    const interval = Number(stored.refreshIntervalMinutes);

    return {
      data,
      lastSuccessfulFetches,
      refreshIntervalMinutes: REFRESH_INTERVALS.includes(interval) ? interval : 60,
    };
  } catch (error) {
    console.warn("Could not restore the saved official-data snapshot:", error);
    return null;
  }
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="glass-card rounded-2xl p-6 text-center">
      <p className="text-sm text-slate-500 dark:text-slate-400">{message}</p>
    </div>
  );
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [data, setData] = useState<DashboardData>({
    gdp: null,
    cpi: null,
    wpi: null,
    iip: null,
    summary: null,
  });
  const dataRef = useRef(data);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(true);
  const [status, setStatus] = useState<DatasetStatus>("UPDATING");
  const [lastSuccessfulFetch, setLastSuccessfulFetch] = useState<string | null>(null);
  const [datasetWarnings, setDatasetWarnings] = useState<string[]>([]);
  const [refreshIntervalMinutes, setRefreshIntervalMinutes] = useState(60);
  const refreshIntervalRef = useRef(refreshIntervalMinutes);
  refreshIntervalRef.current = refreshIntervalMinutes;
  const lastSuccessfulFetchesRef = useRef<Partial<Record<IndicatorDataset, string>>>({});
  const requestRef = useRef<Promise<void> | null>(null);

  const loadData = useCallback((force = true): Promise<void> => {
    if (requestRef.current) return requestRef.current;

    const operation = (async () => {
      const hasExistingData = Object.values(dataRef.current).some((value) => value !== null);
      setLoading(!hasExistingData);
      setRefreshing(true);
      setStatus("UPDATING");

      const [gdp, cpi, wpi, iip] = await Promise.all([
        fetchDataset<GDPDataPoint[]>("/api/gdp", "gdp", force),
        fetchDataset<CPIDataPoint[]>("/api/cpi", "cpi", force),
        fetchDataset<WPIDataPoint[]>("/api/wpi", "wpi", force),
        fetchDataset<IIPDataPoint[]>("/api/iip", "iip", force),
      ]);
      const results: Array<[IndicatorDataset, DatasetFetch<unknown>]> = [
        ["gdp", gdp],
        ["cpi", cpi],
        ["wpi", wpi],
        ["iip", iip],
      ];
      setDatasetWarnings(
        results.flatMap(([key, result]) =>
          result.error ? [`${key.toUpperCase()}: ${result.error}`] : []
        )
      );
      const indicatorData = {
        gdp: gdp.data ?? dataRef.current.gdp,
        cpi: cpi.data ?? dataRef.current.cpi,
        wpi: wpi.data ?? dataRef.current.wpi,
        iip: iip.data ?? dataRef.current.iip,
      };
      const hasIndicatorData = Object.values(indicatorData).some((value) => value !== null);
      const nextData: DashboardData = {
        ...indicatorData,
        summary: hasIndicatorData
          ? buildSummaryStats(
              indicatorData.gdp ?? [],
              indicatorData.cpi ?? [],
              indicatorData.wpi ?? [],
              indicatorData.iip ?? []
            )
          : null,
      };
      const nextFetchTimes = { ...lastSuccessfulFetchesRef.current };
      for (const [key, result] of results) {
        if (result.lastSuccessfulFetch) nextFetchTimes[key] = result.lastSuccessfulFetch;
      }

      dataRef.current = nextData;
      lastSuccessfulFetchesRef.current = nextFetchTimes;
      setData(nextData);
      setLoading(false);

      const fullyFresh = results.every(
        ([, result]) => result.status === "LIVE" && result.data !== null
      );
      const hasUsableData = Object.values(nextData).some((value) => value !== null);
      setStatus(fullyFresh ? "LIVE" : hasUsableData ? "STALE" : "OFFLINE");

      const usableFetchTimes = Object.entries(nextFetchTimes)
        .filter(([key]) => nextData[key as IndicatorDataset] !== null)
        .map(([, timestamp]) => Date.parse(timestamp))
        .filter(Number.isFinite);
      const latestCommonFetch =
        usableFetchTimes.length > 0 ? new Date(Math.min(...usableFetchTimes)).toISOString() : null;
      setLastSuccessfulFetch(latestCommonFetch);

      try {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            data: nextData,
            lastSuccessfulFetches: nextFetchTimes,
            refreshIntervalMinutes: refreshIntervalRef.current,
          } satisfies StoredDashboard)
        );
      } catch (error) {
        console.warn("Could not save the official-data snapshot:", error);
      }
    })().finally(() => {
      setRefreshing(false);
      requestRef.current = null;
    });

    requestRef.current = operation;
    return operation;
  }, []);

  useEffect(() => {
    const stored = getStoredDashboard();
    if (stored) {
      dataRef.current = stored.data;
      lastSuccessfulFetchesRef.current = stored.lastSuccessfulFetches;
      setData(stored.data);
      setRefreshIntervalMinutes(stored.refreshIntervalMinutes);
      const previousFetches = Object.values(stored.lastSuccessfulFetches)
        .map((timestamp) => Date.parse(timestamp))
        .filter(Number.isFinite);
      setLastSuccessfulFetch(
        previousFetches.length > 0 ? new Date(Math.min(...previousFetches)).toISOString() : null
      );
      setStatus(Object.values(stored.data).some((value) => value !== null) ? "STALE" : "OFFLINE");
      setLoading(false);
    }

    void loadData(true);
  }, [loadData]);

  useEffect(() => {
    const intervalId = window.setInterval(
      () => void loadData(true),
      refreshIntervalMinutes * 60 * 1000
    );
    return () => window.clearInterval(intervalId);
  }, [loadData, refreshIntervalMinutes]);

  const showChart = (chart: TabId) => activeTab === "overview" || activeTab === chart;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0b0f1a] mesh-gradient">
      <Header
        activeTab={activeTab}
        onTabChange={setActiveTab}
        status={status}
        lastSuccessfulFetch={lastSuccessfulFetch}
        refreshing={refreshing}
        onRefresh={() => void loadData(true)}
        refreshIntervalMinutes={refreshIntervalMinutes}
        onRefreshIntervalChange={setRefreshIntervalMinutes}
      />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Title */}
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3 }}
          className="mb-8"
        >
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            {sectionDescriptions[activeTab].title}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            {sectionDescriptions[activeTab].subtitle}
          </p>
        </motion.div>

        {datasetWarnings.length > 0 && (
          <output className="mb-6 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-xs text-amber-900 dark:border-amber-800/50 dark:bg-amber-950/30 dark:text-amber-200">
            <p className="font-semibold">Some official data could not be refreshed.</p>
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              {datasetWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </output>
        )}

        {/* Full-page skeleton for overview while loading */}
        {loading && activeTab === "overview" ? (
          <DashboardSkeleton />
        ) : (
          <>
            {/* Summary Cards - visible on overview */}
            {activeTab === "overview" && (
              <section className="mb-10">
                {data.summary ? (
                  <SummaryCards stats={data.summary} />
                ) : (
                  <ErrorBanner message="Summary data temporarily unavailable" />
                )}
              </section>
            )}

            {/* Charts */}
            <AnimatePresence mode="wait">
              <div className="space-y-6">
                {activeTab === "anomalies" && (
                  <section key="anomalies">
                    <AnomalyDashboard />
                  </section>
                )}

                {activeTab === "research" && (
                  <section key="research">
                    <ResearchAssistant />
                  </section>
                )}

                {activeTab === "analysis" && (
                  <section key="analysis">
                    <EconomicAnalysisDashboard />
                  </section>
                )}

                {activeTab === "forecasts" && (
                  <section key="forecasts">
                    <ForecastDashboard />
                  </section>
                )}

                {showChart("gdp") && (
                  <section key="gdp">
                    {loading ? (
                      <ChartSkeleton />
                    ) : data.gdp && data.gdp.length > 0 ? (
                      <GDPChart data={data.gdp} />
                    ) : (
                      <ErrorBanner message="GDP data temporarily unavailable" />
                    )}
                  </section>
                )}

                {activeTab === "overview" && (
                  <div key="cpi-wpi-grid" className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                    <section>
                      {data.cpi && data.cpi.length > 0 ? (
                        <CPIChart data={data.cpi} />
                      ) : (
                        <ErrorBanner message="CPI data temporarily unavailable" />
                      )}
                    </section>
                    <section>
                      {data.wpi && data.wpi.length > 0 ? (
                        <WPIChart data={data.wpi} />
                      ) : (
                        <ErrorBanner message="WPI data temporarily unavailable" />
                      )}
                    </section>
                  </div>
                )}

                {activeTab === "cpi" && (
                  <section key="cpi-full">
                    {loading ? (
                      <ChartSkeleton />
                    ) : data.cpi && data.cpi.length > 0 ? (
                      <CPIChart data={data.cpi} />
                    ) : (
                      <ErrorBanner message="CPI data temporarily unavailable" />
                    )}
                  </section>
                )}

                {activeTab === "wpi" && (
                  <section key="wpi-full">
                    {loading ? (
                      <ChartSkeleton />
                    ) : data.wpi && data.wpi.length > 0 ? (
                      <WPIChart data={data.wpi} />
                    ) : (
                      <ErrorBanner message="WPI data temporarily unavailable" />
                    )}
                  </section>
                )}

                {showChart("iip") && (
                  <section key="iip">
                    {loading ? (
                      <ChartSkeleton />
                    ) : data.iip && data.iip.length > 0 ? (
                      <IIPChart data={data.iip} />
                    ) : (
                      <ErrorBanner message="IIP data temporarily unavailable" />
                    )}
                  </section>
                )}
              </div>
            </AnimatePresence>
          </>
        )}

        {/* Footer */}
        <footer className="mt-16 pt-8 border-t border-slate-200/60 dark:border-slate-700/30">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-0.5">
                <div className="w-1 h-4 bg-india-saffron rounded-full" />
                <div className="w-1 h-4 bg-slate-200 dark:bg-slate-700 rounded-full" />
                <div className="w-1 h-4 bg-india-green rounded-full" />
              </div>
              <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
                India Economic Dashboard
              </span>
            </div>
            <div className="flex items-center gap-4 text-xs text-slate-400 dark:text-slate-500">
              <span>
                Source:{" "}
                <a
                  href="https://esankhyiki.mospi.gov.in/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-india-saffron hover:underline font-medium"
                >
                  Ministry of Statistics and Programme Implementation (MoSPI)
                </a>
              </span>
              <span className="hidden sm:inline">|</span>
              {lastSuccessfulFetch && (
                <span className="hidden sm:inline">
                  Last successful API fetch{" "}
                  {new Date(lastSuccessfulFetch).toLocaleString("en-IN", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </span>
              )}
            </div>
          </div>
          <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-4 text-center leading-relaxed">
            The timestamp above is the last successful data fetch, not the official publication
            date. Chart labels identify statistical observation periods; MoSPI response data does
            not provide official release dates. These statistics are published periodically, not
            continuously. For official statistics, visit{" "}
            <a
              href="https://mospi.gov.in/"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              mospi.gov.in
            </a>
          </p>
        </footer>
      </main>
    </div>
  );
}
