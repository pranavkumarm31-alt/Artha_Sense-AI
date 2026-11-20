"use client";

import type { DatasetStatus } from "@/lib/types";
import { useTheme } from "./theme-provider";

type TabId =
  | "overview"
  | "gdp"
  | "cpi"
  | "wpi"
  | "iip"
  | "forecasts"
  | "analysis"
  | "anomalies"
  | "research";

interface HeaderProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  status: DatasetStatus;
  lastSuccessfulFetch: string | null;
  refreshing: boolean;
  onRefresh: () => void;
  refreshIntervalMinutes: number;
  onRefreshIntervalChange: (minutes: number) => void;
}

const tabs: { id: TabId; label: string; shortLabel: string }[] = [
  { id: "overview", label: "Overview", shortLabel: "All" },
  { id: "gdp", label: "GDP", shortLabel: "GDP" },
  { id: "cpi", label: "CPI", shortLabel: "CPI" },
  { id: "wpi", label: "WPI", shortLabel: "WPI" },
  { id: "iip", label: "IIP", shortLabel: "IIP" },
  { id: "forecasts", label: "AI Forecasts", shortLabel: "Forecasts" },
  { id: "analysis", label: "Economic Analysis", shortLabel: "Analysis" },
  { id: "anomalies", label: "Anomaly Detection", shortLabel: "Anomalies" },
  { id: "research", label: "Research Assistant", shortLabel: "Research" },
];

export type { TabId };

const statusStyles: Record<DatasetStatus, string> = {
  LIVE: "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200/60 dark:border-emerald-800/40 text-emerald-700 dark:text-emerald-400",
  UPDATING:
    "bg-blue-50 dark:bg-blue-950/40 border-blue-200/60 dark:border-blue-800/40 text-blue-700 dark:text-blue-400",
  STALE:
    "bg-amber-50 dark:bg-amber-950/40 border-amber-200/60 dark:border-amber-800/40 text-amber-700 dark:text-amber-400",
  OFFLINE:
    "bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300",
};

function formatFetchTime(value: string | null): string {
  if (!value) return "No successful fetch yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Last successful fetch unavailable"
    : `Last successful fetch ${date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}`;
}

export function Header({
  activeTab,
  onTabChange,
  status,
  lastSuccessfulFetch,
  refreshing,
  onRefresh,
  refreshIntervalMinutes,
  onRefreshIntervalChange,
}: HeaderProps) {
  const { theme, toggleTheme, mounted } = useTheme();

  return (
    <header className="sticky top-0 z-50 border-b border-slate-200/60 dark:border-slate-700/40 bg-white/70 dark:bg-slate-950/70 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo and branding */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-0.5 shrink-0">
              <div className="w-1.5 h-7 bg-india-saffron rounded-full" />
              <div className="w-1.5 h-7 bg-white border border-slate-200 dark:border-slate-600 rounded-full" />
              <div className="w-1.5 h-7 bg-india-green rounded-full" />
            </div>
            <div className="min-w-0">
              <h1 className="text-lg font-bold text-slate-900 dark:text-white tracking-tight truncate">
                India Economic Dashboard
              </h1>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 hidden sm:block">
                Ministry of Statistics & Programme Implementation
              </p>
            </div>
          </div>

          {/* Navigation tabs - desktop */}
          <nav className="hidden md:flex items-center" aria-label="Main navigation">
            <div className="flex items-center bg-slate-100/80 dark:bg-slate-800/60 rounded-xl p-1 gap-0.5">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onTabChange(tab.id)}
                  className={`
                    relative px-4 py-1.5 text-sm font-medium rounded-lg transition-all duration-200
                    ${
                      activeTab === tab.id
                        ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm"
                        : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                    }
                  `}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </nav>

          {/* Right side actions */}
          <div className="flex items-center gap-3">
            <a
              href="https://esankhyiki.mospi.gov.in/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-india-saffron dark:hover:text-saffron-400 transition-colors hidden lg:flex items-center gap-1.5"
            >
              <svg
                className="w-3.5 h-3.5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"
                />
              </svg>
              eSankhyiki
            </a>

            <div className="flex flex-col items-end leading-tight" aria-live="polite">
              <span
                title="LIVE means the latest available official release was fetched successfully; observations are published periodically."
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-semibold ${statusStyles[status]}`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    status === "LIVE"
                      ? "bg-emerald-500"
                      : status === "UPDATING"
                        ? "bg-blue-500 animate-pulse"
                        : status === "STALE"
                          ? "bg-amber-500"
                          : "bg-slate-400"
                  }`}
                />
                {status}
              </span>
              <span className="mt-1 hidden text-[9px] text-slate-500 dark:text-slate-400 sm:inline">
                {status === "STALE"
                  ? "Showing cached official observations"
                  : status === "UPDATING"
                    ? "Refreshing official observations"
                    : status === "OFFLINE"
                      ? "MoSPI unavailable"
                      : "Latest official MoSPI releases"}
              </span>
              <span className="hidden text-[9px] text-slate-400 dark:text-slate-500 md:block">
                {formatFetchTime(lastSuccessfulFetch)}
              </span>
            </div>

            <label className="hidden lg:flex items-center gap-1 text-[10px] text-slate-500 dark:text-slate-400">
              Auto
              <select
                value={refreshIntervalMinutes}
                onChange={(event) => onRefreshIntervalChange(Number(event.target.value))}
                className="rounded-md border border-slate-200 bg-white px-1.5 py-1 text-[10px] text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                aria-label="Automatic refresh interval"
              >
                <option value={15}>15 min</option>
                <option value={60}>1 hour</option>
                <option value={360}>6 hours</option>
              </select>
            </label>

            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              className="rounded-lg border border-slate-200/70 bg-white/70 px-2.5 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700/60 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:bg-slate-800"
              aria-label="Refresh official data"
              title="Fetch the latest available official observations from MoSPI"
            >
              {refreshing ? "Updating..." : "Refresh"}
            </button>

            {/* Theme toggle */}
            <button
              type="button"
              onClick={toggleTheme}
              className="p-2 rounded-xl bg-slate-100/80 dark:bg-slate-800/60 hover:bg-slate-200/80 dark:hover:bg-slate-700/60 transition-all duration-200 border border-slate-200/60 dark:border-slate-700/40"
              aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
            >
              {!mounted ? (
                <div className="w-4 h-4" />
              ) : theme === "light" ? (
                <svg
                  className="w-4 h-4 text-slate-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
                  />
                </svg>
              ) : (
                <svg
                  className="w-4 h-4 text-slate-300"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>

        {/* Mobile tab navigation */}
        <nav
          className="md:hidden flex items-center gap-1 pb-3 overflow-x-auto scrollbar-none -mx-4 px-4"
          aria-label="Main navigation"
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`
                shrink-0 px-3.5 py-1.5 text-xs font-medium rounded-lg transition-all duration-200
                ${
                  activeTab === tab.id
                    ? "bg-india-saffron/10 text-india-saffron dark:bg-saffron-500/15 dark:text-saffron-400 border border-india-saffron/20 dark:border-saffron-500/20"
                    : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/60"
                }
              `}
            >
              {tab.shortLabel}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
