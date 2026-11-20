import {
  compareCalendarMonths,
  compareFiscalQuarters,
  formatFiscalQuarter,
  formatMonthShort,
  formatMonthlyObservation,
  getFiscalYear,
  getMonthIndex,
  isFiscalQuarter,
  isFiscalYear,
} from "./date-utils";
import { type CacheResult, getOrFetchCachedResult } from "./mcp-cache";
import { callTool, extractData, initSession } from "./mcp-client";
import { buildSummaryStats } from "./summary-stats";
import type { CPIDataPoint, GDPDataPoint, IIPDataPoint, SummaryStats, WPIDataPoint } from "./types";

// --------------------------------------------------
// CONFIGURATION
// --------------------------------------------------

const RECENT_CALENDAR_YEAR_COUNT = 4;
const RECENT_GDP_FINANCIAL_YEAR_COUNT = 4;
const ALL_MONTH_CODES = Array.from({ length: 12 }, (_, index) => String(index + 1)).join(",");
const MOSPI_USER_QUERY =
  "Latest available official GDP, CPI, WPI and IIP observations for dashboard";

function makeCacheKey(dataset: string, filters: Record<string, string>): string {
  const sortedFilters = Object.fromEntries(
    Object.entries(filters).sort(([first], [second]) => first.localeCompare(second))
  );
  return `${dataset}:${JSON.stringify(sortedFilters)}`;
}

const CACHE_KEYS = {
  gdp: makeCacheKey("gdp-nas-v5", {
    base_year: "2011-12",
    series: "Current",
    frequency_code: "2",
    indicators: "1,5,21,22",
    quarters: "1,2,3,4",
    recentFinancialYears: String(RECENT_GDP_FINANCIAL_YEAR_COUNT),
  }),
  cpi: makeCacheKey("cpi-v4", {
    base_year: "2024",
    series: "Current",
    level: "Group",
    state: "All India",
    sector: "Combined",
    division: "CPI (General)",
    recentCalendarYears: String(RECENT_CALENDAR_YEAR_COUNT),
  }),
  wpi: makeCacheKey("wpi-yoy-v5", {
    base_year: "2022-23",
    major_group: "Wholesale Price Index",
    recentCalendarYears: String(RECENT_CALENDAR_YEAR_COUNT),
    comparisonYears: "1",
  }),
  iip: makeCacheKey("iip-sectoral-v4", {
    base_year: "2011-12",
    frequency: "Monthly",
    categories: "General,Mining,Manufacturing,Electricity",
    recentCalendarYears: String(RECENT_CALENDAR_YEAR_COUNT),
  }),
} as const;

// --------------------------------------------------
// RAW MOSPI RESPONSE TYPES
// --------------------------------------------------

interface NASGDPGrowthRow {
  year: string;
  quarter: string;
  constant_price: string;
  current_price: string;
  revision?: string | null;
}

interface NASGVAGrowthRow {
  year: string;
  quarter: string;
  industry: string;
  constant_price: string;
}

interface NASGVALevelRow {
  year: string;
  quarter: string;
  industry: string;
  constant_price: string;
}

interface NASGDPAbsoluteRow {
  year: string;
  quarter: string;
  current_price: string;
}

interface CPIRow {
  base_year?: string;
  series?: string;
  year: string | number;
  month: string;
  state?: string;
  sector?: string;
  group?: string;
  subgroup?: string;
  division?: string;
  index: unknown;
  inflation: unknown;
}

interface WPIRow {
  base_year?: string;
  year: number | string;
  month: string;
  major_group: string;
  group: string | null;
  sub_group: string | null;
  sub_sub_group: string | null;
  item: string | null;
  index_value: string;
}

interface IIPRow {
  base_year?: string;
  year: number | string;
  month?: string;
  type: string;
  category: string;
  sub_category: string;
  index: string;
  growth_rate: string | null;
}

type DatasetResult<T> = CacheResult<T>;

// --------------------------------------------------
// COMMON HELPERS
// --------------------------------------------------

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function matchesExpectedLabel(value: unknown, ...expected: string[]): boolean {
  if (value === undefined || value === null) return true;
  const normalized = String(value).trim().toLowerCase();
  return expected.some((label) => normalized === label.toLowerCase());
}

function round2(value: number | null): number | null {
  if (value === null) return null;
  return Math.round(value * 100) / 100;
}

function calculateYearOverYearInflation(
  currentIndex: number | null,
  previousIndex: number | undefined
): number | null {
  if (
    currentIndex === null ||
    previousIndex === undefined ||
    currentIndex <= 0 ||
    previousIndex <= 0
  ) {
    return null;
  }

  return round2(((currentIndex - previousIndex) / previousIndex) * 100);
}

function getMetadataEntries(
  result: Awaited<ReturnType<typeof callTool>>,
  dataset: string,
  dimension: string
): Array<Record<string, unknown>> {
  const metadata = extractData<unknown>(result);
  const groups = Array.isArray(metadata) ? metadata : [metadata];
  const entries = groups.flatMap((group) => {
    if (!group || typeof group !== "object" || Array.isArray(group)) return [];
    const values = (group as Record<string, unknown>)[dimension];
    return Array.isArray(values) ? values : [];
  });
  const records = entries.filter(
    (entry): entry is Record<string, unknown> =>
      Boolean(entry) && typeof entry === "object" && !Array.isArray(entry)
  );

  if (records.length === 0) {
    throw new Error(`MoSPI returned no ${dimension} metadata for ${dataset}`);
  }

  return records;
}

function getTotalPages(result: Awaited<ReturnType<typeof callTool>>): number {
  const metadata = result.structuredContent?.meta_data;

  if (!metadata || typeof metadata !== "object" || !("totalPages" in metadata)) {
    return 1;
  }

  const totalPages = metadata.totalPages;

  if (typeof totalPages !== "number" || !Number.isInteger(totalPages) || totalPages < 0) {
    throw new Error("MoSPI returned invalid pagination metadata");
  }

  return totalPages;
}

function getMetadataYears(result: Awaited<ReturnType<typeof callTool>>, dataset: string): string[] {
  const metadata = extractData<unknown>(result);
  const groups = Array.isArray(metadata) ? metadata : [metadata];
  const values = groups.flatMap((group) => {
    if (!group || typeof group !== "object" || Array.isArray(group)) return [];
    const years = (group as Record<string, unknown>).year;
    return Array.isArray(years) ? years : [];
  });
  const years = values
    .filter(
      (entry) =>
        !entry ||
        typeof entry !== "object" ||
        !("series" in entry) ||
        String(entry.series).toLowerCase() === "current"
    )
    .map((entry) =>
      entry && typeof entry === "object" && "year" in entry ? String(entry.year) : String(entry)
    )
    .filter((year) => /^\d{4}(?:-\d{2})?$/.test(year));

  if (years.length === 0) {
    throw new Error(`MoSPI returned no usable reporting years for ${dataset}`);
  }

  return [...new Set(years)].sort((a, b) => Number(b.slice(0, 4)) - Number(a.slice(0, 4)));
}

function getLatestCalendarYears(years: string[], count: number): string[] {
  return years.filter((year) => /^\d{4}$/.test(year)).slice(0, count);
}

function getMetadataCode(
  result: Awaited<ReturnType<typeof callTool>>,
  dataset: string,
  dimension: string,
  label: string,
  codeKey: string
): string {
  const entry = getMetadataEntries(result, dataset, dimension).find((candidate) =>
    Object.entries(candidate).some(
      ([key, value]) =>
        key !== codeKey && String(value).trim().toLowerCase() === label.toLowerCase()
    )
  );
  const code = entry?.[codeKey];

  if (code === undefined || code === null || String(code).length === 0) {
    throw new Error(`MoSPI metadata contains no ${codeKey} for ${label} in ${dataset}`);
  }

  return String(code);
}

async function fetchMonthlyRows<T>(
  sessionId: string,
  dataset: string,
  filters: Record<string, string>,
  years: string[],
  requestId: number
): Promise<T[]> {
  const pages = await Promise.all(
    years.map((year, index) =>
      fetchAllPages<T>(
        sessionId,
        dataset,
        {
          ...filters,
          year,
          month_code: ALL_MONTH_CODES,
        },
        requestId + index * 10
      )
    )
  );

  return pages.flat();
}

// --------------------------------------------------
// RATE LIMIT HANDLING AND PAGINATION
// --------------------------------------------------

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

async function callPageWithRetry<T>(
  sessionId: string,
  dataset: string,
  filters: Record<string, string>,
  page: number,
  requestId: number
): Promise<{ result: Awaited<ReturnType<typeof callTool>>; rows: T[] }> {
  const maxRetries = 5;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const result = await callTool(
        sessionId,
        {
          name: "get_data",
          arguments: {
            dataset,
            filters: {
              ...filters,
              page: String(page),
            },
          },
        },
        requestId
      );

      const rows = extractData<T[]>(result);

      if (!Array.isArray(rows)) {
        throw new Error(`MoSPI returned non-array data for ${dataset}, page ${page}`);
      }

      return { result, rows };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);

      const isRetryable =
        /429|too many requests|rate.?limit|ECONNRESET|ECONNREFUSED|fetch failed|502|503|504/i.test(
          message
        ) ||
        (error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError"));

      if (!isRetryable || attempt === maxRetries) {
        throw error;
      }

      const waitTime = 1000 * 2 ** attempt;

      console.warn(
        `[MoSPI] Transient failure for ${dataset}, page ${page}. ` +
          `Retry ${attempt + 1}/${maxRetries} after ${waitTime}ms`
      );

      await delay(waitTime);
    }
  }

  throw new Error(`Failed to fetch ${dataset}, page ${page}`);
}

async function fetchPageWithRetry<T>(
  sessionId: string,
  dataset: string,
  filters: Record<string, string>,
  page: number,
  requestId: number
): Promise<T[]> {
  const { rows } = await callPageWithRetry<T>(sessionId, dataset, filters, page, requestId);
  return rows;
}

async function fetchAllPages<T>(
  sessionId: string,
  dataset: string,
  filters: Record<string, string>,
  requestId: number
): Promise<T[]> {
  console.log(`[MoSPI] Starting ${dataset} data fetch...`);

  const { result: firstResult, rows: firstPage } = await callPageWithRetry<T>(
    sessionId,
    dataset,
    filters,
    1,
    requestId
  );

  const totalPages = getTotalPages(firstResult);
  const allRows: T[] = [...firstPage];

  console.log(`[MoSPI] ${dataset}: ${totalPages} total pages.`);

  for (let page = 2; page <= totalPages; page++) {
    await delay(1000);

    const rows = await fetchPageWithRetry<T>(
      sessionId,
      dataset,
      filters,
      page,
      requestId + page - 1
    );

    allRows.push(...rows);
  }

  console.log(`[MoSPI] ${dataset}: ${allRows.length} records fetched.`);

  return allRows;
}

// --------------------------------------------------
// GDP FETCHER
// Existing GDP implementation retained
// --------------------------------------------------

async function fetchGDPDataImpl(): Promise<GDPDataPoint[]> {
  const sessionId = await initSession();

  await callTool(
    sessionId,
    { name: "list_datasets", arguments: { user_query: MOSPI_USER_QUERY } },
    2
  );

  await callTool(
    sessionId,
    {
      name: "get_indicators",
      arguments: { dataset: "NAS", user_query: MOSPI_USER_QUERY },
    },
    3
  );

  const metadataResult = await callTool(
    sessionId,
    {
      name: "get_metadata",
      arguments: {
        dataset: "NAS",
        indicator_code: "22",
        frequency_code: "2",
        user_query: MOSPI_USER_QUERY,
      },
    },
    4
  );

  const years = getMetadataYears(metadataResult, "NAS")
    .slice(0, RECENT_GDP_FINANCIAL_YEAR_COUNT)
    .join(",");
  if (!years) throw new Error("MoSPI returned no recent NAS financial years.");

  const [gdpGrowthResult, gvaGrowthResult, gvaLevelsResult, gdpAbsResult] = await Promise.all([
    fetchAllPages<NASGDPGrowthRow>(
      sessionId,
      "NAS",
      {
        base_year: "2011-12",
        series: "Current",
        frequency_code: "Quarterly",
        indicator_code: "22",
        year: years,
        quarterly_code: "1,2,3,4",
        Format: "JSON",
        limit: "100",
      },
      5
    ),
    fetchAllPages<NASGVAGrowthRow>(
      sessionId,
      "NAS",
      {
        base_year: "2011-12",
        series: "Current",
        frequency_code: "Quarterly",
        indicator_code: "21",
        year: years,
        quarterly_code: "1,2,3,4",
        Format: "JSON",
        limit: "100",
      },
      6
    ),
    fetchAllPages<NASGVALevelRow>(
      sessionId,
      "NAS",
      {
        base_year: "2011-12",
        series: "Current",
        frequency_code: "Quarterly",
        indicator_code: "1",
        year: years,
        quarterly_code: "1,2,3,4",
        Format: "JSON",
        limit: "100",
      },
      8
    ),
    fetchAllPages<NASGDPAbsoluteRow>(
      sessionId,
      "NAS",
      {
        base_year: "2011-12",
        series: "Current",
        frequency_code: "Quarterly",
        indicator_code: "5",
        year: years,
        quarterly_code: "1,2,3,4",
        Format: "JSON",
        limit: "100",
      },
      7
    ),
  ]);

  const gdpGrowthRows = gdpGrowthResult;
  const gvaGrowthRows = gvaGrowthResult;
  const gvaLevelRows = gvaLevelsResult;
  const gdpAbsRows = gdpAbsResult;

  const gvaMap = new Map<string, Map<string, number>>();

  for (const row of gvaGrowthRows) {
    const key = `${row.year}_${row.quarter}`;

    if (!gvaMap.has(key)) {
      gvaMap.set(key, new Map());
    }

    const value = parseNumber(row.constant_price);

    if (value !== null) {
      gvaMap.get(key)?.set(row.industry, value);
    }
  }

  const gvaLevelsMap = new Map<string, Map<string, number>>();
  for (const row of gvaLevelRows) {
    const key = `${row.year}_${row.quarter}`;
    const value = parseNumber(row.constant_price);
    if (value === null) continue;

    if (!gvaLevelsMap.has(key)) gvaLevelsMap.set(key, new Map());
    gvaLevelsMap.get(key)?.set(row.industry, value);
  }

  const gdpAbsMap = new Map<string, number>();

  for (const row of gdpAbsRows) {
    const value = parseNumber(row.current_price);

    if (value !== null) {
      gdpAbsMap.set(`${row.year}_${row.quarter}`, value / 100000);
    }
  }

  function getWeightedGVAGrowth(
    year: string,
    quarter: string,
    industries: string[]
  ): number | null {
    const startYear = Number(year.slice(0, 4));
    const previousYear = `${startYear - 1}-${String(startYear).slice(-2)}`;
    const currentLevels = gvaLevelsMap.get(`${year}_${quarter}`);
    const previousLevels = gvaLevelsMap.get(`${previousYear}_${quarter}`);
    if (!currentLevels || !previousLevels) return null;

    let currentTotal = 0;
    let previousTotal = 0;
    for (const industry of industries) {
      const current = currentLevels.get(industry);
      const previous = previousLevels.get(industry);
      if (current === undefined || previous === undefined || previous <= 0) return null;
      currentTotal += current;
      previousTotal += previous;
    }

    return previousTotal > 0
      ? round2(((currentTotal - previousTotal) / previousTotal) * 100)
      : null;
  }

  const uniqueGdpRows = new Map<string, NASGDPGrowthRow>();
  for (const row of gdpGrowthRows) {
    if (
      parseNumber(row.constant_price) !== null &&
      isFiscalYear(row.year) &&
      isFiscalQuarter(row.quarter)
    ) {
      uniqueGdpRows.set(`${row.year}_${row.quarter}`, row);
    }
  }

  const sortedGdp = [...uniqueGdpRows.values()].sort(compareFiscalQuarters);

  const result: GDPDataPoint[] = sortedGdp.map((row) => {
    const key = `${row.year}_${row.quarter}`;
    const industries = gvaMap.get(key);
    const agriculture = industries?.get("Agriculture, Livestock, Forestry and Fishing") ?? null;

    return {
      quarter: row.quarter,
      year: row.year,
      period: formatFiscalQuarter(row.quarter, row.year),
      gdpGrowth: round2(parseNumber(row.constant_price)),
      gvaAgriculture: round2(agriculture),
      gvaIndustry: getWeightedGVAGrowth(row.year, row.quarter, [
        "Mining and Quarrying",
        "Manufacturing",
        "Electricity, Gas, Water Supply & Other Utility Services",
        "Construction",
      ]),
      gvaServices: getWeightedGVAGrowth(row.year, row.quarter, [
        "Trade, Hotels, Transport, Communication & Services Related to Broadcasting",
        "Financial, Real Estate & Professional Services",
        "Public Administration, Defence & Other Services",
      ]),
      gdpNominal: round2(gdpAbsMap.get(key) ?? null),
      estimateStatus: row.revision ? String(row.revision) : null,
    };
  });

  if (result.length === 0) throw new Error("MoSPI returned no valid GDP quarterly observations.");

  return result;
}

export function fetchGDPData(force = false): Promise<DatasetResult<GDPDataPoint[]>> {
  return getOrFetchCachedResult(CACHE_KEYS.gdp, fetchGDPDataImpl, { force });
}

// --------------------------------------------------
// CPI FETCHER
// Base year: 2024
// All India: state_code 1
// Combined: sector_code 3
// General: division_code resolved from metadata
// --------------------------------------------------

async function fetchCPIDataImpl(): Promise<CPIDataPoint[]> {
  const sessionId = await initSession();

  await callTool(
    sessionId,
    { name: "list_datasets", arguments: { user_query: MOSPI_USER_QUERY } },
    2
  );

  await callTool(
    sessionId,
    {
      name: "get_indicators",
      arguments: { dataset: "CPI", user_query: MOSPI_USER_QUERY },
    },
    3
  );

  const metadataResult = await callTool(
    sessionId,
    {
      name: "get_metadata",
      arguments: {
        dataset: "CPI",
        base_year: "2024",
        level: "Group",
        user_query: MOSPI_USER_QUERY,
      },
    },
    4
  );

  const availableYears = getLatestCalendarYears(
    getMetadataYears(metadataResult, "CPI"),
    RECENT_CALENDAR_YEAR_COUNT + 1
  );
  const outputYears = availableYears.slice(0, RECENT_CALENDAR_YEAR_COUNT);
  if (outputYears.length === 0) throw new Error("MoSPI returned no recent CPI calendar years.");

  const commonFilters = {
    base_year: "2024",
    series: "Current",
    state_code: getMetadataCode(metadataResult, "CPI", "state", "All India", "state_code"),
    sector_code: getMetadataCode(metadataResult, "CPI", "sector", "Combined", "sector_code"),
    division_code: getMetadataCode(
      metadataResult,
      "CPI",
      "division",
      "CPI (General)",
      "division_code"
    ),
    limit: "100",
    Format: "JSON",
  };

  const rows = await fetchMonthlyRows<CPIRow>(sessionId, "CPI", commonFilters, availableYears, 5);
  const generalRows = rows.filter((row) => {
    return (
      matchesExpectedLabel(row.base_year, "2024") &&
      matchesExpectedLabel(row.series, "Current") &&
      matchesExpectedLabel(row.state, "All India") &&
      matchesExpectedLabel(row.sector, "Combined") &&
      matchesExpectedLabel(row.division, "CPI (General)", "General")
    );
  });
  const uniqueRows = new Map<string, CPIRow>();

  for (const row of generalRows) {
    const calendarYear = String(row.year);
    if (
      !/^\d{4}$/.test(calendarYear) ||
      getMonthIndex(row.month) < 0 ||
      parseNumber(row.index) === null
    ) {
      continue;
    }

    const key = `${calendarYear}_${getMonthIndex(row.month)}`;
    uniqueRows.set(key, row);
  }

  const indexByPeriod = new Map<string, number>();
  for (const row of uniqueRows.values()) {
    const index = parseNumber(row.index);
    if (index !== null) {
      indexByPeriod.set(`${row.year}_${getMonthIndex(row.month)}`, index);
    }
  }

  const cpiResult: CPIDataPoint[] = [...uniqueRows.values()]
    .filter((row) => outputYears.includes(String(row.year)))
    .map((row) => {
      const calendarYear = String(row.year);
      const monthIndex = getMonthIndex(row.month);
      const currentIndex = parseNumber(row.index);
      const previousIndex = indexByPeriod.get(`${Number(calendarYear) - 1}_${monthIndex}`);
      const officialInflation = parseNumber(row.inflation);
      const calculatedInflation = calculateYearOverYearInflation(currentIndex, previousIndex);
      const inflationSource: CPIDataPoint["inflationSource"] =
        officialInflation !== null
          ? "official"
          : calculatedInflation !== null
            ? "calculated"
            : null;

      return {
        month: formatMonthShort(row.month),
        year: calendarYear,
        fiscalYear: getFiscalYear(calendarYear, row.month),
        period: formatMonthlyObservation(row.month, calendarYear),
        cpiGeneral: currentIndex,
        cpiFood: null,
        cpiFuel: null,
        cpiHousing: null,
        cpiClothing: null,
        inflationRate: round2(officialInflation) ?? calculatedInflation,
        inflationSource,
      };
    })
    .sort(compareCalendarMonths);

  if (cpiResult.length === 0) {
    throw new Error("MoSPI returned no valid CPI General observations.");
  }

  console.log(
    `[MoSPI] CPI: ${cpiResult.length} monthly observations across ${outputYears.length} years.`
  );

  return cpiResult;
}

export function fetchCPIData(force = false): Promise<DatasetResult<CPIDataPoint[]>> {
  return getOrFetchCachedResult(CACHE_KEYS.cpi, fetchCPIDataImpl, { force });
}

// --------------------------------------------------
// WPI FETCHER
// Base year: 2022-23
// Overall WPI major group: 1000000000
// --------------------------------------------------

async function fetchWPIDataImpl(): Promise<WPIDataPoint[]> {
  const sessionId = await initSession();

  await callTool(
    sessionId,
    { name: "list_datasets", arguments: { user_query: MOSPI_USER_QUERY } },
    2
  );

  await callTool(
    sessionId,
    {
      name: "get_indicators",
      arguments: { dataset: "WPI", user_query: MOSPI_USER_QUERY },
    },
    3
  );

  const metadataResult = await callTool(
    sessionId,
    {
      name: "get_metadata",
      arguments: { dataset: "WPI", base_year: "2022-23", user_query: MOSPI_USER_QUERY },
    },
    4
  );

  const availableYears = getLatestCalendarYears(
    getMetadataYears(metadataResult, "WPI"),
    RECENT_CALENDAR_YEAR_COUNT + 1
  );
  const outputYears = availableYears.slice(0, RECENT_CALENDAR_YEAR_COUNT);
  if (outputYears.length === 0) throw new Error("MoSPI returned no recent WPI calendar years.");

  const commonFilters = {
    base_year: "2022-23",
    major_group_code: getMetadataCode(
      metadataResult,
      "WPI",
      "major_group",
      "Wholesale Price Index",
      "major_group_code"
    ),
    limit: "100",
    Format: "JSON",
  };

  const rows = await fetchMonthlyRows<WPIRow>(sessionId, "WPI", commonFilters, availableYears, 5);

  const overallRows = rows.filter(
    (row) =>
      matchesExpectedLabel(row.base_year, "2022-23") &&
      matchesExpectedLabel(row.major_group, "Wholesale Price Index") &&
      !row.group &&
      !row.sub_group &&
      !row.sub_sub_group &&
      !row.item
  );

  const uniqueRows = new Map<string, WPIRow>();

  for (const row of overallRows) {
    if (!/^\d{4}$/.test(String(row.year)) || getMonthIndex(row.month) < 0) continue;
    uniqueRows.set(`${row.year}_${getMonthIndex(row.month)}`, row);
  }

  const indexByPeriod = new Map<string, number>();

  for (const row of uniqueRows.values()) {
    const monthIndex = getMonthIndex(row.month);
    const index = parseNumber(row.index_value);

    if (monthIndex >= 0 && index !== null) {
      indexByPeriod.set(`${row.year}_${monthIndex}`, index);
    }
  }

  const wpiResult: WPIDataPoint[] = [...uniqueRows.values()]
    .filter((row) => outputYears.includes(String(row.year)))
    .map((row) => {
      const monthIndex = getMonthIndex(row.month);
      const currentIndex = parseNumber(row.index_value);
      const previousIndex =
        monthIndex < 0 ? undefined : indexByPeriod.get(`${Number(row.year) - 1}_${monthIndex}`);
      const calendarYear = String(row.year);
      const inflation = calculateYearOverYearInflation(currentIndex, previousIndex);
      const inflationSource: WPIDataPoint["wpiInflationSource"] =
        inflation === null ? null : "calculated";

      return {
        month: formatMonthShort(row.month),
        year: calendarYear,
        fiscalYear: getFiscalYear(calendarYear, row.month),
        period: formatMonthlyObservation(row.month, calendarYear),
        wpiAll: currentIndex,
        wpiPrimary: null,
        wpiFuel: null,
        wpiManufactured: null,
        wpiInflation: inflation,
        wpiInflationSource: inflationSource,
      };
    })
    .sort(compareCalendarMonths);

  if (wpiResult.length === 0) {
    throw new Error("MoSPI returned no valid overall WPI observations.");
  }

  const comparableObservations = wpiResult.filter((row) => row.wpiInflation !== null).length;
  console.log(
    `[MoSPI] WPI: ${wpiResult.length} monthly observations across ${outputYears.length} years, ` +
      `${comparableObservations} with prior-year matches.`
  );

  return wpiResult;
}

export function fetchWPIData(force = false): Promise<DatasetResult<WPIDataPoint[]>> {
  return getOrFetchCachedResult(CACHE_KEYS.wpi, fetchWPIDataImpl, { force });
}

// --------------------------------------------------
// IIP FETCHER
// Base year: 2011-12
// Type: General
// Category code: 4
// --------------------------------------------------

async function fetchIIPDataImpl(): Promise<IIPDataPoint[]> {
  const sessionId = await initSession();

  await callTool(
    sessionId,
    { name: "list_datasets", arguments: { user_query: MOSPI_USER_QUERY } },
    2
  );

  await callTool(
    sessionId,
    {
      name: "get_indicators",
      arguments: { dataset: "IIP", user_query: MOSPI_USER_QUERY },
    },
    3
  );

  const metadataResult = await callTool(
    sessionId,
    {
      name: "get_metadata",
      arguments: {
        dataset: "IIP",
        base_year: "2011-12",
        frequency: "Monthly",
        user_query: MOSPI_USER_QUERY,
      },
    },
    4
  );

  const years = getLatestCalendarYears(
    getMetadataYears(metadataResult, "IIP"),
    RECENT_CALENDAR_YEAR_COUNT
  );
  if (years.length === 0) throw new Error("MoSPI returned no recent IIP calendar years.");

  const commonFilters = {
    base_year: "2011-12",
    frequency: "Monthly",
    limit: "100",
    Format: "JSON",
  };
  const categories = [
    { key: "general", name: "General", type: "General", requestId: 5 },
    { key: "mining", name: "Mining", type: "Sectoral", requestId: 45 },
    { key: "manufacturing", name: "Manufacturing", type: "Sectoral", requestId: 85 },
    { key: "electricity", name: "Electricity", type: "Sectoral", requestId: 125 },
  ] as const;
  const categoryCodes = Object.fromEntries(
    categories.map(({ name }) => [
      name,
      getMetadataCode(metadataResult, "IIP", "category", name, "category_code"),
    ])
  );

  const [generalRows, ...sectorResults] = await Promise.all([
    fetchMonthlyRows<IIPRow>(
      sessionId,
      "IIP",
      {
        ...commonFilters,
        type: "General",
        category_code: categoryCodes.General,
      },
      years,
      5
    ),
    ...categories.slice(1).map(({ name, type, requestId }) =>
      fetchMonthlyRows<IIPRow>(
        sessionId,
        "IIP",
        {
          ...commonFilters,
          type,
          category_code: categoryCodes[name],
        },
        years,
        requestId
      ).then(
        (rows) => ({ name, rows }),
        (error: unknown) => ({ name, error })
      )
    ),
  ]);

  const toTopLevelMap = (
    rows: IIPRow[],
    category: string,
    expectedType: string
  ): Map<string, IIPRow> => {
    const mapped = new Map<string, IIPRow>();
    for (const row of rows) {
      if (
        !matchesExpectedLabel(row.base_year, "2011-12") ||
        !matchesExpectedLabel(row.type, expectedType) ||
        !matchesExpectedLabel(row.category, category) ||
        String(row.sub_category ?? "").trim() !== "" ||
        !/^\d{4}$/.test(String(row.year)) ||
        !row.month ||
        getMonthIndex(row.month) < 0
      ) {
        continue;
      }

      mapped.set(`${row.year}_${getMonthIndex(row.month)}`, row);
    }
    return mapped;
  };
  const generalByPeriod = toTopLevelMap(generalRows, "General", "General");
  const sectorMaps = new Map<string, Map<string, IIPRow>>();
  for (const result of sectorResults) {
    if ("error" in result) {
      console.warn(`[MoSPI] IIP ${result.name} observations unavailable:`, result.error);
      continue;
    }
    sectorMaps.set(result.name, toTopLevelMap(result.rows, result.name, "Sectoral"));
  }

  const iipResult: IIPDataPoint[] = [...generalByPeriod.entries()]
    .map(([periodKey, row]) => {
      const period = periodKey.split("_");
      const calendarYear = period[0];
      const monthIndex = Number(period[1]);
      const month = formatMonthShort(String(monthIndex + 1));
      const fiscalYear = getFiscalYear(calendarYear, month);
      const getSectorIndex = (name: string): number | null => {
        const sectorRow = sectorMaps.get(name)?.get(periodKey);
        return sectorRow ? parseNumber(sectorRow.index) : null;
      };

      return {
        month: formatMonthShort(row.month ?? ""),
        year: calendarYear,
        fiscalYear,
        period: formatMonthlyObservation(row.month ?? "", calendarYear),
        iipGeneral: parseNumber(row.index),
        iipMining: getSectorIndex("Mining"),
        iipManufacturing: getSectorIndex("Manufacturing"),
        iipElectricity: getSectorIndex("Electricity"),
        growthRate: round2(parseNumber(row.growth_rate)),
      };
    })
    .sort(compareCalendarMonths);

  if (iipResult.length === 0) {
    throw new Error("MoSPI returned no valid IIP General observations.");
  }

  console.log(
    `[MoSPI] IIP: ${iipResult.length} monthly observations across ${years.length} years.`
  );

  return iipResult;
}

export function fetchIIPData(force = false): Promise<DatasetResult<IIPDataPoint[]>> {
  return getOrFetchCachedResult(CACHE_KEYS.iip, fetchIIPDataImpl, { force });
}

// --------------------------------------------------
// SUMMARY STATISTICS
// --------------------------------------------------

export async function fetchSummaryStats(force = false): Promise<DatasetResult<SummaryStats>> {
  const results = await Promise.allSettled([
    fetchGDPData(force),
    fetchCPIData(force),
    fetchWPIData(force),
    fetchIIPData(force),
  ]);
  const sourceWarnings: string[] = [];
  const getData = <T>(result: PromiseSettledResult<DatasetResult<T[]>>, dataset: string): T[] => {
    if (result.status === "fulfilled") {
      if (result.value.status === "stale") {
        sourceWarnings.push(
          `${dataset}: ${result.value.warning ?? "cached observations are being shown"}`
        );
      }
      return result.value.data;
    }
    console.error(`[MoSPI] ${dataset} unavailable for summary:`, result.reason);
    sourceWarnings.push(`${dataset}: official source unavailable`);
    return [];
  };

  const [gdpResult, cpiResult, wpiResult, iipResult] = results;
  const gdpData = getData(gdpResult, "GDP");
  const cpiData = getData(cpiResult, "CPI");
  const wpiData = getData(wpiResult, "WPI");
  const iipData = getData(iipResult, "IIP");
  const successfulResults = results.flatMap((result) =>
    result.status === "fulfilled" ? [result.value] : []
  );
  if (successfulResults.length === 0) {
    throw new Error("MoSPI summary is unavailable because all indicator sources failed.");
  }

  const summary = buildSummaryStats(gdpData, cpiData, wpiData, iipData);
  const lastSuccessfulFetch = new Date(
    Math.min(...successfulResults.map((result) => Date.parse(result.lastSuccessfulFetch)))
  ).toISOString();
  const allFresh = sourceWarnings.length === 0;

  return {
    data: summary,
    status: allFresh ? "live" : "stale",
    lastSuccessfulFetch,
    ...(allFresh
      ? {}
      : { warning: `Summary data may be incomplete. ${sourceWarnings.join("; ")}` }),
  };
}
