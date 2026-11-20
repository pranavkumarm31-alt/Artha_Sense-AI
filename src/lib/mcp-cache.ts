export type CacheStatus = "live" | "stale";

export interface CacheResult<T> {
  data: T;
  status: CacheStatus;
  lastSuccessfulFetch: string;
  warning?: string;
}

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

interface CacheState {
  entries: Map<string, CacheEntry<unknown>>;
  inFlight: Map<string, Promise<unknown>>;
  queue: Promise<void>;
}

const globalCache = globalThis as typeof globalThis & {
  __indiaEconomicDashboardCache?: CacheState;
};

function getCacheState(): CacheState {
  const existing = globalCache.__indiaEconomicDashboardCache;
  if (existing) {
    if (!existing.queue) existing.queue = Promise.resolve();
    return existing;
  }

  const state: CacheState = {
    entries: new Map<string, CacheEntry<unknown>>(),
    inFlight: new Map<string, Promise<unknown>>(),
    queue: Promise.resolve(),
  };
  globalCache.__indiaEconomicDashboardCache = state;
  return state;
}

const cacheState = getCacheState();
const DEFAULT_TTL = Number(process.env.MOSPI_CACHE_TTL_MS ?? 6 * 60 * 60 * 1000);

if (!Number.isFinite(DEFAULT_TTL) || DEFAULT_TTL <= 0) {
  throw new Error("MOSPI_CACHE_TTL_MS must be a positive number of milliseconds.");
}

function toCacheResult<T>(entry: CacheEntry<T>, status: CacheStatus): CacheResult<T> {
  return {
    data: entry.data,
    status,
    lastSuccessfulFetch: new Date(entry.timestamp).toISOString(),
  };
}

export function getCacheResult<T>(key: string): CacheResult<T> | null {
  const entry = cacheState.entries.get(key) as CacheEntry<T> | undefined;
  if (!entry) return null;

  const status = Date.now() - entry.timestamp <= entry.ttl ? "live" : "stale";
  return toCacheResult(entry, status);
}

export function getCached<T>(key: string): T | null {
  const result = getCacheResult<T>(key);
  return result?.status === "live" ? result.data : null;
}

export function setCache<T>(key: string, data: T, ttl = DEFAULT_TTL): CacheResult<T> {
  const entry = { data, timestamp: Date.now(), ttl };
  cacheState.entries.set(key, entry);
  return toCacheResult(entry, "live");
}

export function getOrFetchCachedResult<T>(
  key: string,
  fetcher: () => Promise<T>,
  options: { force?: boolean } = {}
): Promise<CacheResult<T>> {
  const cached = getCacheResult<T>(key);
  if (!options.force && cached?.status === "live") return Promise.resolve(cached);

  const inFlight = cacheState.inFlight.get(key);
  if (inFlight) return inFlight as Promise<CacheResult<T>>;

  const request = cacheState.queue
    .then(async () => {
      if (!options.force) {
        const latest = getCacheResult<T>(key);
        if (latest?.status === "live") return latest;
      }

      try {
        return setCache(key, await fetcher());
      } catch (error) {
        const fallback = getCacheResult<T>(key);
        if (!fallback) throw error;

        console.warn(`[MoSPI] Refresh failed; serving stale ${key} cache.`, error);
        return {
          ...fallback,
          status: "stale" as const,
          warning: "Refresh failed; showing the last successful official observations.",
        };
      }
    })
    .finally(() => cacheState.inFlight.delete(key));

  cacheState.queue = request.then(
    () => undefined,
    () => undefined
  );
  cacheState.inFlight.set(key, request);
  return request;
}

export async function getOrFetchCached<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const result = await getOrFetchCachedResult(key, fetcher);
  return result.data;
}

export function clearCache(): void {
  cacheState.entries.clear();
}
