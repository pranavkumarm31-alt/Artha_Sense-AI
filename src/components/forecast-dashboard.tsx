"use client";

import type { ForecastIndicator, ForecastModel, ForecastResponse } from "@/lib/types";
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

const indicators: { value: ForecastIndicator; label: string }[] = [
  { value: "gdp_real_growth", label: "GDP Growth" },
  { value: "cpi_inflation", label: "CPI Inflation" },
  { value: "wpi_inflation", label: "WPI Inflation" },
  { value: "iip_growth", label: "IIP Growth" },
];

const models: { value: ForecastModel; label: string }[] = [
  { value: "naive", label: "Naive" },
  { value: "seasonal_naive", label: "Seasonal Naive" },
  { value: "arima", label: "ARIMA" },
  { value: "sarima", label: "SARIMA" },
  { value: "random_forest", label: "Random Forest" },
  { value: "xgboost", label: "XGBoost" },
];

interface HistoricalPoint {
  observation_period: string;
  observation_start: string;
  value: number;
}

interface HistoryResponse {
  historical: HistoricalPoint[];
  forecasts: Array<{
    observation_period: string;
    observation_start: string;
    value: number;
    lower_bound: number | null;
    upper_bound: number | null;
  }>;
}

export function ForecastDashboard() {
  const [indicator, setIndicator] = useState<ForecastIndicator>("gdp_real_growth");
  const [model, setModel] = useState<ForecastModel>("naive");
  const [horizon, setHorizon] = useState(2);
  const [result, setResult] = useState<ForecastResponse | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [comparison, setComparison] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/forecasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ indicator_code: indicator, model, horizon, persist: true }),
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error ?? "Forecast generation failed.");
      setResult(payload as ForecastResponse);
    } catch (requestError) {
      setResult(null);
      setError(requestError instanceof Error ? requestError.message : "Forecast unavailable.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setHorizon(indicator === "gdp_real_growth" ? 2 : 3);
  }, [indicator]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(`/api/forecasts?indicator=${indicator}&view=history&model=${model}`, {
        cache: "no-store",
      }).then((response) => response.json()),
      fetch(`/api/forecasts?indicator=${indicator}&view=compare`, {
        cache: "no-store",
      }).then((response) => response.json()),
    ])
      .then(([historyPayload, comparisonPayload]) => {
        if (cancelled) return;
        if (!historyPayload.error) setHistory(historyPayload as HistoryResponse);
        if (!comparisonPayload.error) {
          setComparison((comparisonPayload.models ?? []) as Record<string, unknown>[]);
        }
      })
      .catch(() => {
        if (!cancelled) setError("Could not retrieve saved forecast data.");
      });
    return () => {
      cancelled = true;
    };
  }, [indicator, model]);

  const chartData = [
    ...(history?.historical ?? []).slice(-30).map((point) => ({
      period: point.observation_period,
      historical: point.value,
      forecast: null,
      lower: null,
      upper: null,
    })),
    ...(history?.forecasts ?? []).map((point) => ({
      period: point.observation_period,
      historical: null,
      forecast: point.value,
      lower: point.lower_bound,
      upper: point.upper_bound,
    })),
  ];

  const horizonOptions =
    indicator === "gdp_real_growth"
      ? [
          { value: 1, label: "1 quarter" },
          { value: 2, label: "2 quarters" },
          { value: 4, label: "4 quarters" },
        ]
      : [
          { value: 1, label: "1 month" },
          { value: 3, label: "3 months" },
          { value: 6, label: "6 months" },
          { value: 12, label: "12 months" },
        ];

  return (
    <div className="space-y-6">
      <section className="glass-card rounded-2xl p-5">
        <div className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end">
          <label className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Economic indicator
            <select
              value={indicator}
              onChange={(event) => setIndicator(event.target.value as ForecastIndicator)}
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
            Forecast model
            <select
              value={model}
              onChange={(event) => setModel(event.target.value as ForecastModel)}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            >
              {models.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            Forecast horizon
            <select
              value={horizon}
              onChange={(event) => setHorizon(Number(event.target.value))}
              className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            >
              {horizonOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => void generate()}
            disabled={loading}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-60 dark:bg-white dark:text-slate-900"
          >
            {loading ? "Generating..." : "Generate forecast"}
          </button>
        </div>
      </section>

      {error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          {error}
        </div>
      )}

      <section className="glass-card rounded-2xl p-5">
        <div className="mb-4">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            Historical vs Forecast
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Forecasts use persisted official observations. Intervals shown only when the model
            provides or estimates them.
          </p>
        </div>
        <div className="h-80">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                <XAxis dataKey="period" tick={{ fontSize: 11 }} minTickGap={20} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="historical"
                  name="Historical"
                  stroke="#64748b"
                  dot={false}
                />
                <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#f97316" dot />
                <Line
                  type="monotone"
                  dataKey="lower"
                  name="Lower interval"
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="upper"
                  name="Upper interval"
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              No saved observations or forecasts are available.
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="glass-card rounded-2xl p-5">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">Forecast summary</h3>
          {result ? (
            <div className="mt-4 space-y-2 text-sm">
              <p>
                <strong>Status:</strong> {result.status}
              </p>
              <p>
                <strong>Training observations:</strong> {result.training_observation_count}
              </p>
              {result.metrics && (
                <p>
                  <strong>Walk-forward MAE:</strong> {result.metrics.mae?.toFixed(3) ?? "N/A"}
                </p>
              )}
              {result.warning && (
                <p className="text-amber-700 dark:text-amber-300">{result.warning}</p>
              )}
              {result.forecasts.length > 0 && (
                <p>
                  <strong>Latest forecast:</strong> {result.forecasts.at(-1)?.observation_period}:{" "}
                  {result.forecasts.at(-1)?.value.toFixed(2)}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">
              Generate a forecast to see validated output.
            </p>
          )}
        </section>

        <section className="glass-card rounded-2xl p-5">
          <h3 className="text-base font-bold text-slate-900 dark:text-white">Model performance</h3>
          {comparison.length > 0 ? (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="text-slate-500">
                    <th className="py-2">Model</th>
                    <th>MAE</th>
                    <th>RMSE</th>
                    <th>sMAPE</th>
                    <th>Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.map((row) => {
                    const metrics = row.metrics as Record<string, number | null> | undefined;
                    return (
                      <tr
                        key={String(row.model)}
                        className="border-t border-slate-200/60 dark:border-slate-700/60"
                      >
                        <td className="py-2 font-medium">{String(row.model)}</td>
                        <td>{metrics?.MAE?.toFixed(3) ?? "N/A"}</td>
                        <td>{metrics?.RMSE?.toFixed(3) ?? "N/A"}</td>
                        <td>{metrics?.sMAPE?.toFixed(2) ?? "N/A"}%</td>
                        <td>
                          {metrics?.directional_accuracy != null
                            ? `${metrics.directional_accuracy.toFixed(1)}%`
                            : "N/A"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">No validated model runs yet.</p>
          )}
        </section>
      </div>

      <section className="glass-card rounded-2xl p-5">
        <h3 className="text-base font-bold text-slate-900 dark:text-white">Methodology</h3>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          Chronological rolling-origin validation prevents future observations from entering
          training data. Baselines use the last observation or matching seasonal observation.
          ARIMA/SARIMA use statsmodels. Random Forest and XGBoost use lag features. Prediction
          intervals are statistical confidence intervals for ARIMA/SARIMA or empirical residual
          intervals where enough validation residuals exist.
        </p>
      </section>
    </div>
  );
}
