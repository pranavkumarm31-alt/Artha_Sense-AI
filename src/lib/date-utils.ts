const MONTHS = [
  { long: "January", short: "Jan" },
  { long: "February", short: "Feb" },
  { long: "March", short: "Mar" },
  { long: "April", short: "Apr" },
  { long: "May", short: "May" },
  { long: "June", short: "Jun" },
  { long: "July", short: "Jul" },
  { long: "August", short: "Aug" },
  { long: "September", short: "Sep" },
  { long: "October", short: "Oct" },
  { long: "November", short: "Nov" },
  { long: "December", short: "Dec" },
] as const;

const FISCAL_QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;

export function isFiscalYear(year: string): boolean {
  const match = /^(\d{4})-(\d{2})$/.exec(year);
  return Boolean(match && String(Number(match[1]) + 1).slice(-2) === match[2]);
}

export function isFiscalQuarter(quarter: string): boolean {
  return FISCAL_QUARTERS.includes(quarter as (typeof FISCAL_QUARTERS)[number]);
}

export function getMonthIndex(month: string): number {
  const normalized = month.trim().toLowerCase();
  const namedMonth = MONTHS.findIndex(
    ({ long, short }) => long.toLowerCase() === normalized || short.toLowerCase() === normalized
  );
  if (namedMonth >= 0) return namedMonth;

  const numericMonth = Number(normalized);
  return Number.isInteger(numericMonth) && numericMonth >= 1 && numericMonth <= 12
    ? numericMonth - 1
    : -1;
}

export function formatMonthShort(month: string): string {
  const monthIndex = getMonthIndex(month);
  return monthIndex >= 0 ? MONTHS[monthIndex].short : month.trim();
}

export function getFiscalYear(calendarYear: string, month: string): string {
  const year = Number(calendarYear);
  const monthIndex = getMonthIndex(month);

  if (!Number.isInteger(year) || !/^\d{4}$/.test(calendarYear) || monthIndex < 0) {
    throw new Error(`Invalid reporting date from MoSPI: ${calendarYear} ${month}`);
  }

  const startYear = monthIndex >= 3 ? year : year - 1;
  return `${startYear}-${String(startYear + 1).slice(-2)}`;
}

export function formatMonthlyObservation(month: string, calendarYear: string): string {
  return `${formatMonthShort(month)} ${calendarYear}`;
}

export function formatFiscalQuarter(quarter: string, fiscalYear: string): string {
  return `${quarter} FY ${fiscalYear}`;
}

export function compareFiscalQuarters(
  first: { quarter: string; year: string },
  second: { quarter: string; year: string }
): number {
  const yearOrder = Number(first.year.slice(0, 4)) - Number(second.year.slice(0, 4));
  if (yearOrder !== 0) return yearOrder;
  return (
    FISCAL_QUARTERS.indexOf(first.quarter as (typeof FISCAL_QUARTERS)[number]) -
    FISCAL_QUARTERS.indexOf(second.quarter as (typeof FISCAL_QUARTERS)[number])
  );
}

export function formatMonthlyObservationWithFiscalYear(
  month: string,
  calendarYear: string,
  fiscalYear: string
): string {
  return `${formatMonthlyObservation(month, calendarYear)} (FY ${fiscalYear})`;
}

export function compareCalendarMonths(
  first: { month: string; year: string },
  second: { month: string; year: string }
): number {
  const firstYear = Number(first.year);
  const secondYear = Number(second.year);
  if (firstYear !== secondYear) return firstYear - secondYear;
  return getMonthIndex(first.month) - getMonthIndex(second.month);
}
