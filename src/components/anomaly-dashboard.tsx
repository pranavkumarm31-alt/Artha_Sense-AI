"use client";

import { useCallback, useEffect, useState } from "react";
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

interface Anomaly {
  indicator_code: string;
  indicator_name: string;
  observation_period: string;
  observation_start: string;
  actual_value: number;
  expected_value: number;
  absolute_deviation: number;
  percentage_deviation: number | null;
  anomaly_score: number;
  detection_method: string;
  severity: "low" | "medium" | "high";
  detected_at: string;
  source_name: string | null;
  source_url: string | null;
  model_version: string;
  explanation: string;
}

interface Summary {
  total: number;
  low: number;
  medium: number;
  high: number;
  by_indicator: Record<string, number>;
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

export function AnomalyDashboard() {
  const [indicator, setIndicator] = useState<IndicatorCode>("gdp_real_growth");
  const [method, setMethod] = useState("zscore");
  const [threshold, setThreshold] = useState(2.5);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [detected, setDetected] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ indicator });
      if (start) params.set("start", start);
      if (end) params.set("end", end);
      const [summaryPayload, anomalyPayload] = await Promise.all([
        fetch("/api/anomalies?view=summary", { cache: "no-store" }).then((response) =>
          response.json()
        ),
        fetch(`/api/anomalies?${params.toString()}`, { cache: "no-store" }).then((response) =>
          response.json()
        ),
      ]);
      if (summaryPayload.error) throw new Error(summaryPayload.error);
      if (anomalyPayload.error) throw new Error(anomalyPayload.error);
      setSummary(summaryPayload as Summary);
      setAnomalies(anomalyPayload as Anomaly[]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Anomaly data unavailable.");
    } finally {
      setLoading(false);
    }
  }, [indicator, start, end]);

  useEffect(() => {
    void load();
  }, [load]);

  const detect = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = {
        indicator_code: indicator,
        methods: [method],
        threshold,
        rolling_window: 12,
        contamination: 0.05,
        start: start || null,
        end: end || null,
        persist: true,
      };
      const response = await fetch("/api/anomalies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Anomaly detection failed.");
      setDetected(payload.anomalies ?? []);
      await load();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Anomaly detection failed.");
    } finally {
      setLoading(false);
    }
  };

  const chartData = [
    ...anomalies.map((item) => ({
      period: item.observation_period,
      actual: item.actual_value,
      expected: item.expected_value,
      anomaly: item.actual_value,
    })),
  ];

  const cards = [
    { label: "Total", value: summary?.total ?? 0, color: "text-slate-900 dark:text-white" },
    { label: "High", value: summary?.high ?? 0, color: "text-red-600" },
    { label: "Medium", value: summary?.medium ?? 0, color: "text-amber-600" },
    { label: "Low", value: summary?.low ?? 0, color: "text-blue-600" },
  ];

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="glass-card rounded-2xl p-5">
            <p className="text-xs font-semibold uppercase text-slate-500">{card.label}</p>
            <p className={`mt-2 text-3xl font-bold ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </section>

      <section className="glass-card rounded-2xl p-5">
        <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_1fr_auto] md:items-end">
          <label className="text-xs font-semibold text-slate-500">
            Indicator
            <select
              value={indicator}
              onChange={(event) => setIndicator(event.target.value as IndicatorCode)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              {indicators.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-500">
            Algorithm
            <select
              value={method}
              onChange={(event) => setMethod(event.target.value)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="zscore">Historical Z-score</option>
              <option value="rolling">Rolling Z-score</option>
              <option value="isolation_forest">Isolation Forest</option>
              <option value="seasonal_residual">Seasonal residual</option>
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-500">
            Z-score threshold
            <input
              type="number"
              min="1"
              max="6"
              step="0.1"
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs font-semibold text-slate-500">
              Start
              <input
                type="date"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-2 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
              />
            </label>
            <label className="text-xs font-semibold text-slate-500">
              End
              <input
                type="date"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-2 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
              />
            </label>
          </div>
          <button
            type="button"
            onClick={() => void detect()}
            disabled={loading}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-60 dark:bg-white dark:text-slate-900"
          >
            {loading ? "Running..." : "Run detection"}
          </button>
        </div>
      </section>

      {error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          {error}
        </div>
      )}

      <section className="glass-card rounded-2xl p-5">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">Anomaly timeline</h3>
        <div className="mt-4 h-80">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                <XAxis dataKey="period" tick={{ fontSize: 11 }} minTickGap={24} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="actual" name="Actual" stroke="#64748b" dot={false} />
                <Line
                  type="monotone"
                  dataKey="expected"
                  name="Baseline"
                  stroke="#2563eb"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="anomaly"
                  name="Anomalous value"
                  stroke="#dc2626"
                  dot
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              No persisted anomalies match this indicator and date range.
            </div>
          )}
        </div>
      </section>

      <section className="glass-card rounded-2xl p-5">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">Anomaly details</h3>
        {(detected.length > 0 ? detected : anomalies).length > 0 ? (
          <div className="mt-4 space-y-3">
            {(detected.length > 0 ? detected : anomalies).slice(0, 20).map((item) => (
              <article
                key={`${item.indicator_code}-${item.observation_period}-${item.detection_method}`}
                className="rounded-xl border border-slate-200/70 p-4 dark:border-slate-700/60"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <strong>
                    {item.indicator_name} · {item.observation_period}
                  </strong>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-semibold ${item.severity === "high" ? "bg-red-100 text-red-700" : item.severity === "medium" ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"}`}
                  >
                    {item.severity}
                  </span>
                </div>
                <p className="mt-2 text-sm">
                  Actual {item.actual_value.toFixed(2)} · Baseline {item.expected_value.toFixed(2)}{" "}
                  · Deviation {item.absolute_deviation.toFixed(2)} · Score{" "}
                  {item.anomaly_score.toFixed(3)}
                </p>
                <p className="mt-2 text-xs text-slate-500">{item.explanation}</p>
                <p className="mt-2 text-xs text-slate-400">
                  {item.detection_method} · {item.model_version} ·{" "}
                  {item.source_name && item.source_url ? (
                    <a
                      href={item.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      {item.source_name}
                    </a>
                  ) : (
                    "Source unavailable"
                  )}
                </p>
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-500">No anomaly records detected or persisted.</p>
        )}
      </section>

      {summary && (
        <section className="glass-card rounded-2xl p-5">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            Indicator distribution
          </h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(summary.by_indicator).map(([code, count]) => (
              <span
                key={code}
                className="rounded-full border border-slate-200 px-3 py-1 text-xs dark:border-slate-700"
              >
                {code}: {count}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
