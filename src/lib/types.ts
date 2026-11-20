// GDP / National Accounts data types
export interface GDPDataPoint {
  quarter: string;
  year: string;
  period: string;
  gdpGrowth: number | null;
  gvaAgriculture: number | null;
  gvaIndustry: number | null;
  gvaServices: number | null;
  gdpNominal: number | null; // in lakh crore INR
  estimateStatus: string | null;
}

// Consumer Price Index data types
export interface CPIDataPoint {
  month: string;
  /** Calendar year of the official observation. */
  year: string;
  fiscalYear: string;
  period: string;
  cpiGeneral: number | null;
  cpiFood: number | null;
  cpiFuel: number | null;
  cpiHousing: number | null;
  cpiClothing: number | null;
  inflationRate: number | null;
  inflationSource: "official" | "calculated" | null;
}

// Wholesale Price Index data types
export interface WPIDataPoint {
  month: string;
  /** Calendar year of the official observation. */
  year: string;
  fiscalYear: string;
  period: string;
  wpiAll: number | null;
  wpiPrimary: number | null;
  wpiFuel: number | null;
  wpiManufactured: number | null;
  wpiInflation: number | null;
  wpiInflationSource: "calculated" | null;
}

// Index of Industrial Production data types
export interface IIPDataPoint {
  month: string;
  /** Calendar year of the official observation. */
  year: string;
  fiscalYear: string;
  period: string;
  iipGeneral: number | null;
  iipMining: number | null;
  iipManufacturing: number | null;
  iipElectricity: number | null;
  growthRate: number | null;
}

// Summary statistics
export interface SummaryStats {
  gdpGrowth: {
    value: number | null;
    quarter: string;
    trend: "up" | "down" | "stable";
  };
  cpiInflation: {
    value: number | null;
    month: string;
    trend: "up" | "down" | "stable";
  };
  wpiInflation: {
    value: number | null;
    month: string;
    trend: "up" | "down" | "stable";
  };
  iipGrowth: {
    value: number | null;
    month: string;
    trend: "up" | "down" | "stable";
  };
}

// API response types
export type DatasetStatus = "LIVE" | "UPDATING" | "STALE" | "OFFLINE";

export interface APIResponse<T> {
  data: T | null;
  status: DatasetStatus;
  lastSuccessfulFetch: string | null;
  source: string;
  error?: string;
  metadata?: Record<string, string>;
}

export type ForecastIndicator =
  | "gdp_real_growth"
  | "cpi_inflation"
  | "wpi_inflation"
  | "iip_growth";

export type ForecastModel =
  | "naive"
  | "seasonal_naive"
  | "arima"
  | "sarima"
  | "random_forest"
  | "xgboost";

export interface ForecastPoint {
  observation_period: string;
  observation_start: string;
  horizon: number;
  value: number;
  lower_bound: number | null;
  upper_bound: number | null;
}

export interface ForecastMetrics {
  mae: number | null;
  rmse: number | null;
  smape: number | null;
  directional_accuracy: number | null;
  test_observations: number;
  test_period_start: string | null;
  test_period_end: string | null;
  method: string;
}

export interface ForecastResponse {
  indicator_code: ForecastIndicator;
  model: ForecastModel;
  model_version: string;
  status: "success" | "insufficient_data" | "failed";
  warning: string | null;
  training_observation_count: number;
  training_period_start: string | null;
  training_period_end: string | null;
  metrics: ForecastMetrics | null;
  forecasts: ForecastPoint[];
  persisted: boolean;
}

export interface ForecastComparison {
  indicator_code: ForecastIndicator;
  models: Array<Record<string, unknown>>;
}
