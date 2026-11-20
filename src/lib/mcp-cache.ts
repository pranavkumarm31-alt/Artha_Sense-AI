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

const DEFAULT_TTL = 6 * 60 * 60 * 1000; // 6 hours - data updates monthly/quarterly

export function getCached<T>(key: string): T | null {
  const entry = cacheState.entries.get(key);
  if (!entry) return null;
  if (Date.now() - entry.timestamp > entry.ttl) {
    cacheState.entries.delete(key);
    return null;
  }
  return entry.data as T;
}

export function setCache<T>(key: string, data: T, ttl = DEFAULT_TTL): void {
  cacheState.entries.set(key, { data, timestamp: Date.now(), ttl });
}

export function getOrFetchCached<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const cached = getCached<T>(key);
  if (cached !== null) return Promise.resolve(cached);

  const inFlight = cacheState.inFlight.get(key);
  if (inFlight) return inFlight as Promise<T>;

  const request = cacheState.queue
    .then(fetcher)
    .then((data) => {
      setCache(key, data);
      return data;
    })
    .finally(() => cacheState.inFlight.delete(key));

  cacheState.queue = request.then(
    () => undefined,
    () => undefined
  );
  cacheState.inFlight.set(key, request);
  return request;
}

export function clearCache(): void {
  cacheState.entries.clear();
  cacheState.inFlight.clear();
}
