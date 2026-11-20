const URL = "https://mcp.mospi.gov.in/";
const PROTOCOL = "2025-03-26";

let session = "";
let requestId = 0;

const MONTHS = {
  1: "January",
  2: "February",
  3: "March",
  4: "April",
  5: "May",
  6: "June",
  7: "July",
  8: "August",
  9: "September",
  10: "October",
  11: "November",
  12: "December",
};

const MONTH_NUMBERS = Object.fromEntries(
  Object.entries(MONTHS).map(([number, name]) => [name.toLowerCase(), Number(number)])
);

const DATASETS = {
  CPI: {
    baseYear: "2024",
    buildFilters(year, months) {
      return {
        base_year: "2024",
        series: "Current",
        year: String(year),
        state_code: "1",
        sector_code: "3",
        division_code: "0",
        month_code: months.join(","),
        limit: "100",
      };
    },
  },

  WPI: {
    baseYear: "2022-23",
    buildFilters(year, months) {
      return {
        base_year: "2022-23",
        year: String(year),
        major_group_code: "1000000000",
        month_code: months.join(","),
        limit: "100",
      };
    },
  },

  IIP: {
    baseYear: "2011-12",
    buildFilters(year, months) {
      return {
        base_year: "2011-12",
        year: String(year),
        frequency: "Monthly",
        type: "General",
        category_code: "4",
        month_code: months.join(","),
        limit: "100",
      };
    },
  },
};

// --------------------------------------------------
// MCP REQUEST HANDLING
// --------------------------------------------------

async function post(method, params = {}, notification = false) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL,
  };

  if (session) {
    headers["mcp-session-id"] = session;
  }

  const payload = {
    jsonrpc: "2.0",
    method,
    params,
  };

  if (!notification) {
    payload.id = ++requestId;
  }

  const response = await fetch(URL, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`);
  }

  session ||= response.headers.get("mcp-session-id") || "";

  const text = await response.text();

  if (notification || !text.trim()) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    const dataLine = text
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .filter(Boolean)
      .pop();

    if (dataLine) {
      return JSON.parse(dataLine);
    }

    throw new Error(`Invalid MCP response:\n${text}`);
  }
}

async function initialize() {
  const response = await post("initialize", {
    protocolVersion: PROTOCOL,
    capabilities: {},
    clientInfo: {
      name: "arthasense-data-diagnostic",
      version: "2.0.0",
    },
  });

  if (response.error) {
    throw new Error(JSON.stringify(response.error));
  }

  await post("notifications/initialized", {}, true);

  console.log("MoSPI MCP session initialized successfully.");
}

// --------------------------------------------------
// MCP TOOL CALL
// --------------------------------------------------

async function call(name, args) {
  const response = await post("tools/call", {
    name,
    arguments: args,
  });

  if (response.error) {
    throw new Error(JSON.stringify(response.error));
  }

  if (response.result?.isError) {
    throw new Error(
      response.result.content?.map((item) => item.text || "").join("\n") || `${name} failed`
    );
  }

  const result = response.result;

  if (result?.structuredContent?.data !== undefined) {
    return result.structuredContent.data;
  }

  for (const item of result?.content || []) {
    if (item.text) {
      try {
        return JSON.parse(item.text);
      } catch {
        // Continue checking other response blocks.
      }
    }
  }

  return result;
}

// --------------------------------------------------
// RESPONSE NORMALIZATION
// --------------------------------------------------

function getRows(data) {
  if (Array.isArray(data)) return data;

  if (Array.isArray(data?.data)) return data.data;
  if (Array.isArray(data?.rows)) return data.rows;
  if (Array.isArray(data?.records)) return data.records;

  return [];
}

function getMonthNumber(value) {
  if (typeof value === "number") {
    return value;
  }

  const text = String(value || "")
    .trim()
    .toLowerCase();

  if (/^\d+$/.test(text)) {
    return Number(text);
  }

  return MONTH_NUMBERS[text] || 0;
}

function sortChronologically(rows) {
  return [...rows].sort((a, b) => {
    const yearDifference = Number(a.year) - Number(b.year);

    if (yearDifference !== 0) {
      return yearDifference;
    }

    return getMonthNumber(a.month) - getMonthNumber(b.month);
  });
}

function getUniqueRows(rows) {
  const seen = new Set();

  return rows.filter((row) => {
    const key = JSON.stringify(row);

    if (seen.has(key)) {
      return false;
    }

    seen.add(key);
    return true;
  });
}

// --------------------------------------------------
// DATASET-SPECIFIC VALIDATION
// --------------------------------------------------

function validateRows(dataset, rows, expectedBaseYear) {
  const validRows = [];
  const rejectedRows = [];

  for (const row of rows) {
    const baseYear = String(row.base_year ?? "");

    if (baseYear && baseYear !== expectedBaseYear) {
      rejectedRows.push(row);
      continue;
    }

    if (dataset === "CPI") {
      const correctCPI =
        String(row.series || "").toLowerCase() === "current" &&
        String(row.state || "").toLowerCase() === "all india" &&
        String(row.sector || "").toLowerCase() === "combined" &&
        String(row.division || "")
          .toLowerCase()
          .includes("general");

      if (!correctCPI) {
        rejectedRows.push(row);
        continue;
      }
    }

    if (dataset === "WPI") {
      const group = String(row.major_group || row.major_group_name || "").toLowerCase();

      const code = String(row.major_group_code || row.code || "");

      // If the API supplies group information, verify it.
      if ((group || code) && !group.includes("wholesale price index") && code !== "1000000000") {
        rejectedRows.push(row);
        continue;
      }
    }

    if (dataset === "IIP") {
      const type = String(row.type || "").toLowerCase();
      const category = String(row.category || row.category_name || "").toLowerCase();
      const categoryCode = String(row.category_code || "");

      if (type && !type.includes("general")) {
        rejectedRows.push(row);
        continue;
      }

      if (categoryCode && categoryCode !== "4") {
        rejectedRows.push(row);
        continue;
      }

      if (category && !category.includes("general")) {
        rejectedRows.push(row);
        continue;
      }
    }

    validRows.push(row);
  }

  return { validRows, rejectedRows };
}

// --------------------------------------------------
// LATEST FINANCIAL YEAR FILTER
// --------------------------------------------------

function getFinancialYear(row) {
  const year = Number(row.year);
  const month = getMonthNumber(row.month);
  if (!Number.isInteger(year) || month < 1 || month > 12) return null;

  const startYear = month >= 4 ? year : year - 1;
  return `${startYear}-${String(startYear + 1).slice(-2)}`;
}

function getLatestFinancialYearRows(rows) {
  const years = [...new Set(rows.map(getFinancialYear).filter(Boolean))].sort(
    (a, b) => Number(a.slice(0, 4)) - Number(b.slice(0, 4))
  );
  const financialYear = years.at(-1) || null;

  return {
    financialYear,
    rows: financialYear ? rows.filter((row) => getFinancialYear(row) === financialYear) : [],
  };
}

function getMetadataYears(metadata) {
  const groups = Array.isArray(metadata) ? metadata : [metadata];
  const years = groups.flatMap((group) => {
    if (!group || typeof group !== "object" || !Array.isArray(group.year)) return [];
    return group.year.map((entry) =>
      entry && typeof entry === "object" && "year" in entry ? entry.year : entry
    );
  });

  return [...new Set(years.map(String).filter((year) => /^\d{4}$/.test(year)))].sort(
    (a, b) => Number(b) - Number(a)
  );
}

// --------------------------------------------------
// DATASET FETCHER
// --------------------------------------------------

async function fetchDataset(datasetName, config, requests) {
  const allRows = [];

  console.log(`\n========== FETCHING ${datasetName} ==========`);

  for (const request of requests) {
    const filters = config.buildFilters(request.year, request.months);

    console.log(`\n${datasetName}: ${request.year}, months: ${request.months.join(",")}`);

    console.log("Filters:", filters);

    try {
      const result = await call("get_data", {
        dataset: datasetName,
        filters,
      });

      const rows = getRows(result);

      console.log(`Raw records received: ${rows.length}`);

      if (rows.length > 0) {
        console.log("Sample record:");
        console.log(JSON.stringify(rows[0], null, 2));
      }

      allRows.push(...rows);
    } catch (error) {
      console.error(`${datasetName} ${request.year} ERROR:`, error.message);
    }
  }

  const uniqueRows = getUniqueRows(allRows);

  const { validRows, rejectedRows } = validateRows(datasetName, uniqueRows, config.baseYear);

  console.log(`\n${datasetName} unique records: ${uniqueRows.length}`);
  console.log(`${datasetName} valid records: ${validRows.length}`);
  console.log(`${datasetName} rejected records: ${rejectedRows.length}`);

  if (rejectedRows.length > 0) {
    console.log("First rejected record:");
    console.log(JSON.stringify(rejectedRows[0], null, 2));
  }

  return sortChronologically(validRows);
}

// --------------------------------------------------
// OUTPUT
// --------------------------------------------------

function printResults(datasetName, rows, baseYear) {
  console.log(`\n\n========== ${datasetName} RESULTS ==========`);

  console.log("Expected base year:", baseYear);
  console.log("Total unique valid observations:", rows.length);

  if (!rows.length) {
    console.log("No valid observations returned.");
    return;
  }

  const baseYears = [...new Set(rows.map((row) => row.base_year).filter(Boolean))];

  console.log("Returned base years:", baseYears);

  const { financialYear, rows: latestYearRows } = getLatestFinancialYearRows(rows);

  console.log(`\nLATEST FINANCIAL YEAR${financialYear ? ` (${financialYear})` : ""}:`);
  console.log("Available months:", latestYearRows.length);

  console.table(
    latestYearRows.map((row) => ({
      year: row.year,
      month: row.month,
      base_year: row.base_year,
      index: row.index ?? row.index_value ?? row.general_index ?? null,
      inflation: row.inflation ?? row.growth_rate ?? null,
      major_group: row.major_group ?? null,
      category: row.category ?? null,
      type: row.type ?? null,
    }))
  );

  console.log("\nLATEST 10 OBSERVATIONS:");

  console.table(
    rows
      .slice(-10)
      .reverse()
      .map((row) => ({
        year: row.year,
        month: row.month,
        base_year: row.base_year,
        index: row.index ?? row.index_value ?? row.general_index ?? null,
        inflation: row.inflation ?? row.growth_rate ?? null,
      }))
  );

  console.log("\nFULL DATA:");
  console.log(JSON.stringify(rows, null, 2));
}

// --------------------------------------------------
// MAIN
// --------------------------------------------------

async function main() {
  await initialize();

  const datasetNames = ["CPI", "WPI", "IIP"];
  const metadataByDataset = {};

  // Fetch metadata independently.
  for (const name of datasetNames) {
    console.log(`\n========== ${name} METADATA ==========`);

    try {
      const metadata = await call("get_metadata", {
        dataset: name,
      });
      metadataByDataset[name] = metadata;

      console.log(JSON.stringify(metadata, null, 2).slice(0, 6000));
    } catch (error) {
      console.error(`${name} metadata error:`, error.message);
    }
  }

  const results = {};

  for (const name of datasetNames) {
    const years = getMetadataYears(metadataByDataset[name]).slice(0, 4);
    const requests = years.map((year) => ({
      year,
      months: Array.from({ length: 12 }, (_, index) => index + 1),
    }));
    results[name] = await fetchDataset(name, DATASETS[name], requests);

    printResults(name, results[name], DATASETS[name].baseYear);
  }

  console.log("\n\n========== FINAL SUMMARY ==========");

  for (const name of datasetNames) {
    const { financialYear, rows } = getLatestFinancialYearRows(results[name]);

    console.log(
      `${name}: ${rows.length} latest-FY observations${financialYear ? ` (${financialYear})` : ""}`
    );
  }

  console.log("\nMoSPI diagnostic completed.");
}

main().catch((error) => {
  console.error("\nDIAGNOSTIC FAILED:");
  console.error(error);
  process.exitCode = 1;
});
