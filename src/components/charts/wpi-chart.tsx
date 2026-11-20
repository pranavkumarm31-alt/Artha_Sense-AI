"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useChartTheme } from "@/components/ui/chart-tooltip";
import type { WPIDataPoint } from "@/lib/types";
import { motion } from "framer-motion";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface WPIChartProps {
  data: WPIDataPoint[];
}

export function WPIChart({ data }: WPIChartProps) {
  const { grid, axis, tick, tooltipStyle } = useChartTheme();

  const chartData = data.map((d) => ({
    period: d.period,
    inflation: d.wpiInflation,
    all: d.wpiAll,
  }));
  const hasInflationData = data.some(
    (point) => point.wpiInflation !== null && Number.isFinite(point.wpiInflation)
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.3 }}
    >
      <Card className="chart-container">
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center text-white shadow-sm">
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M20 12H4m16 0l-4-4m4 4l-4 4M4 12l4-4M4 12l4 4"
                />
              </svg>
            </div>
            <div>
              <CardTitle>Wholesale Price Index (WPI)</CardTitle>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Monthly overall WPI and year-on-year inflation (Base: 2022-23=100)
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-72">
            <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-3 uppercase tracking-wider">
              WPI Inflation Rate (%)
            </h4>
            {hasInflationData ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <defs>
                    <linearGradient id="wpiBarGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.7} />
                      <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.3} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={grid}
                    strokeOpacity={0.5}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="period"
                    tick={{ fontSize: 11, fill: tick }}
                    tickLine={false}
                    axisLine={{ stroke: axis, strokeWidth: 1 }}
                    dy={8}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: tick }}
                    tickLine={false}
                    axisLine={false}
                    unit="%"
                    domain={["auto", "auto"]}
                    width={45}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value) => [
                      typeof value === "number" ? `${value.toFixed(2)}%` : "N/A",
                    ]}
                  />
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    wrapperStyle={{ fontSize: "12px", paddingTop: "12px" }}
                  />
                  <Bar
                    dataKey="inflation"
                    name="WPI Inflation"
                    fill="url(#wpiBarGradient)"
                    radius={[6, 6, 0, 0]}
                    barSize={24}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="pt-8 text-sm text-slate-500 dark:text-slate-400">
                Year-on-year inflation is unavailable because matching prior-year index observations
                were not returned.
              </p>
            )}
            {hasInflationData && (
              <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
                Calculated from the same month one year earlier; months without a match are omitted.
              </p>
            )}
          </div>

          <div className="mt-8 pt-6 border-t border-slate-200/60 dark:border-slate-700/30">
            <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-3 uppercase tracking-wider">
              Overall WPI Index (2022-23=100)
            </h4>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke={grid}
                    strokeOpacity={0.5}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="period"
                    tick={{ fontSize: 10, fill: tick }}
                    tickLine={false}
                    axisLine={{ stroke: axis, strokeWidth: 1 }}
                    dy={8}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: tick }}
                    tickLine={false}
                    axisLine={false}
                    domain={["auto", "auto"]}
                    width={45}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value) => [typeof value === "number" ? value.toFixed(1) : "N/A"]}
                  />
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    wrapperStyle={{ fontSize: "11px", paddingTop: "12px" }}
                  />
                  <Line
                    type="monotone"
                    dataKey="all"
                    name="All Commodities"
                    stroke="#6366f1"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
