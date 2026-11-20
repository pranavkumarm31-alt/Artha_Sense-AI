"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type IndicatorCode =
  | "gdp_real_growth"
  | "gva_agriculture"
  | "gva_industry"
  | "gva_services"
  | "cpi_inflation"
  | "wpi_inflation"
  | "iip_growth";

interface AnalysisPoint {
  observation_start: string;
  observation_period: string;
  value: number;
  period_change: number | null;
  year_on_year_change: number | null;
  moving_average_3: number | null;
  moving_average_6: number | null;
  moving_average_12: number | null;
  rolling_volatility_3: number | null;
  deviation_from_ma: number | null;
}

interface TrendResponse {
  indicator_code: IndicatorCode;
  frequency: "monthly" | "quarterly";
  observation_count: number;
  sample_start: string | null;
  sample_end: string | null;
  trend: string;
  change_direction: string;
  latest: AnalysisPoint | null;
  series: AnalysisPoint[];
  methodology: string;
}

interface Correlation {
  left_indicator: IndicatorCode;
  right_indicator: IndicatorCode;
  correlation: number | null;
  sample_size: number;
  alignment: string;
  caveat: string;
}

interface Insight {
  indicator: string;
  observation_period: string;
  actual_value: number;
  comparison_period: string;
  comparison_value: number;
  magnitude: number;
  magnitude_unit: string;
  year_on_year_change: number | null;
  classification: "positive" | "negative" | "neutral";
  evidence_strength: "high" | "limited";
  trend: string;
  insight: string;
  calculation: string;
  source: string;
  source_url: string;
  interpretation: string;
}

const indicators: { value: IndicatorCode; label: string }[] = [
  { value: "gdp_real_growth", label: "GDP Growth" },
  { value: "gva_agriculture", label: "GVA Agriculture" },
  { value: "gva_industry", label: "GVA Industry" },
  { value: "gva_services", label: "GVA Services" },
  { value: "cpi_inflation", label: "CPI Inflation" },
  { value: "wpi_inflation", label: "WPI Inflation" },
  { value: "iip_growth", label: "IIP Growth" },
];

export function EconomicAnalysisDashboard() {
  const [indicator, setIndicator] = useState<IndicatorCode>("gdp_real_growth");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [trend, setTrend] = useState<TrendResponse | null>(null);
  const [correlations, setCorrelations] = useState<Correlation[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [sectors, setSectors] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ indicator });
    if (start) params.set("start", start);
    if (end) params.set("end", end);

    Promise.all([
      fetch(`/api/analysis?view=trends&${params.toString()}`).then((response) => response.json()),
      fetch(
        `/api/analysis?view=correlations&${start ? `start=${start}&` : ""}${end ? `end=${end}` : ""}`
      ).then((response) => response.json()),
      fetch(
        `/api/analysis?view=insights&${start ? `start=${start}&` : ""}${end ? `end=${end}` : ""}`
      ).then((response) => response.json()),
      fetch(
        `/api/analysis?view=sectors&${start ? `start=${start}&` : ""}${end ? `end=${end}` : ""}`
      ).then((response) => response.json()),
    ])
      .then(([trendPayload, correlationPayload, insightPayload, sectorPayload]) => {
        if (cancelled) return;
        if (trendPayload.error) throw new Error(trendPayload.error);
        setTrend(trendPayload as TrendResponse);
        setCorrelations(Array.isArray(correlationPayload) ? correlationPayload : []);
        setInsights(Array.isArray(insightPayload) ? insightPayload : []);
        setSectors(Array.isArray(sectorPayload.sectors) ? sectorPayload.sectors : []);
      })
      .catch((requestError) => {
        if (!cancelled)
          setError(requestError instanceof Error ? requestError.message : "Analysis unavailable.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [indicator, start, end]);

  const chartData = (trend?.series ?? []).map((point) => ({
    period: point.observation_period,
    value: point.value,
    movingAverage3: point.moving_average_3,
    movingAverage6: point.moving_average_6,
    periodChange: point.period_change,
    yearOnYear: point.year_on_year_change,
  }));

  const classificationStyles: Record<Insight["classification"], string> = {
    positive:
      "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300",
    negative:
      "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300",
    neutral:
      "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
  };

  return (
    <div className="space-y-6">
      <section className="glass-card rounded-2xl p-5">
        <div className="grid gap-4 md:grid-cols-4 md:items-end">
          <label className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Indicator
            <select
              value={indicator}
              onChange={(event) => setIndicator(event.target.value as IndicatorCode)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            >
              {indicators.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Start date
            <input
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </label>
          <label className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            End date
            <input
              type="date"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setStart("");
              setEnd("");
            }}
            className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-slate-700 dark:text-slate-300"
          >
            Reset date range
          </button>
        </div>
      </section>

      {error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          {error}
        </div>
      )}

      {loading ? (
        <div className="glass-card rounded-2xl p-8 text-center text-sm text-slate-500">
          Analyzing persisted observations...
        </div>
      ) : (
        <>
          <section className="glass-card rounded-2xl p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  Historical trend and moving averages
                </h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {trend?.frequency === "quarterly" ? "Quarterly" : "Monthly"} official observations
                </p>
              </div>
              {trend && (
                <div className="flex gap-2 text-xs">
                  <span className="rounded-full border px-3 py-1">Trend: {trend.trend}</span>
                  <span className="rounded-full border px-3 py-1">
                    Change: {trend.change_direction}
                  </span>
                  <span className="rounded-full border px-3 py-1">N={trend.observation_count}</span>
                </div>
              )}
            </div>
            <div className="h-80">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                    <XAxis dataKey="period" tick={{ fontSize: 11 }} minTickGap={24} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend />
                    <Line
                      type="monotone"
                      dataKey="value"
                      name="Observation"
                      stroke="#64748b"
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="movingAverage3"
                      name="3-period MA"
                      stroke="#2563eb"
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="movingAverage6"
                      name="6-period MA"
                      stroke="#f97316"
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-500">
                  No observations are available for this indicator and date range.
                </div>
              )}
            </div>
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="glass-card rounded-2xl p-5">
              <h3 className="text-base font-bold text-slate-900 dark:text-white">
                Correlation analysis
              </h3>
              {correlations.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {correlations.map((item) => (
                    <div
                      key={`${item.left_indicator}-${item.right_indicator}`}
                      className="rounded-xl border border-slate-200/70 p-3 text-sm dark:border-slate-700/60"
                    >
                      <div className="flex justify-between gap-3">
                        <strong>
                          {item.left_indicator} vs {item.right_indicator}
                        </strong>
                        <span>
                          {item.correlation === null ? "N/A" : item.correlation.toFixed(3)}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        N={item.sample_size} · {item.alignment}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">{item.caveat}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  No aligned correlations are available.
                </p>
              )}
            </section>

            <section className="glass-card rounded-2xl p-5">
              <h3 className="text-base font-bold text-slate-900 dark:text-white">
                Sector analysis
              </h3>
              {sectors.length > 0 ? (
                <div className="mt-4 space-y-3">
                  {sectors.map((sector) => (
                    <div
                      key={String(sector.sector)}
                      className="flex items-center justify-between rounded-xl border border-slate-200/70 p-3 text-sm dark:border-slate-700/60"
                    >
                      <div>
                        <strong>{String(sector.sector)}</strong>
                        <p className="text-xs text-slate-500">
                          Trend: {String(sector.trend)} · N={String(sector.observation_count)}
                        </p>
                      </div>
                      <span>
                        {String(
                          (sector.latest as Record<string, unknown> | undefined)?.value ?? "N/A"
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-slate-500">
                  No GVA sector observations are currently persisted.
                </p>
              )}
            </section>
          </div>

          <section className="glass-card rounded-2xl p-5">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              Economic insights
            </h3>
            {insights.length > 0 ? (
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                {insights.map((insight) => (
                  <article
                    key={`${insight.indicator}-${insight.observation_period}`}
                    className={`rounded-xl border p-4 ${classificationStyles[insight.classification]}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <strong>{insight.indicator}</strong>
                      <span className="text-xs uppercase">{insight.classification}</span>
                    </div>
                    <p className="mt-2 text-sm">{insight.insight}</p>
                    <p className="mt-2 text-xs opacity-80">
                      Calculation: {insight.calculation}. {insight.interpretation}
                    </p>
                    <p className="mt-2 text-xs">
                      Evidence: {insight.evidence_strength} ·{" "}
                      <a
                        href={insight.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="underline"
                      >
                        {insight.source}
                      </a>
                    </p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">
                No meaningful latest-period insights are available.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
