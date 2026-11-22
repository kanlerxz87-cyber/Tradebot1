// Kalshi demo REST client.
//
// Every host and every field name used here was checked against the official
// Kalshi documentation and against live responses from the demo API on
// 2026-11-22. The source for each item is listed in SOURCES below and mirrored
// in data/sources.json and on the site's Sources page.
//
// IMPORTANT: this module is used by the GitHub Actions collector, which has
// normal internet egress. The Arena build sandbox used to author this repo
// could NOT reach the Kalshi hosts from a shell (TLS reset), so nothing here is
// exercised against the live API during development. Offline tests use
// fixtures; the CI run is what proves the client works end to end. That
// limitation is flagged on the site (see flagged.html, F-01).

export const DEMO_REST_ROOTS = [
  'https://external-api.demo.kalshi.co/trade-api/v2',
  'https://demo-api.kalshi.co/trade-api/v2',
];

export const PRODUCTION_REST_ROOTS = [
  'https://external-api.kalshi.com/trade-api/v2',
  'https://api.elections.kalshi.com/trade-api/v2',
];

// The demo environment docs list both demo roots as supported, with
// external-api.demo first. https://docs.kalshi.com/getting_started/demo_env
export const DEFAULT_ROOT = DEMO_REST_ROOTS[0];

export const SOURCES = {
  environments: 'https://docs.kalshi.com/getting_started/api_environments',
  demoEnv: 'https://docs.kalshi.com/getting_started/demo_env',
  markets: 'https://docs.kalshi.com/api-reference/market/get-markets',
  market: 'https://docs.kalshi.com/api-reference/market/get-market',
  events: 'https://docs.kalshi.com/api-reference/events/get-events',
  orderbook: 'https://docs.kalshi.com/api-reference/market/get-market-orderbook',
  candlesticks: 'https://docs.kalshi.com/api-reference/market/get-market-candlesticks',
  seriesList: 'https://docs.kalshi.com/api-reference/market/get-series-list',
  series: 'https://docs.kalshi.com/api-reference/market/get-series',
  lifecycle: 'https://docs.kalshi.com/getting_started/market_lifecycle',
  orderbookSemantics: 'https://docs.kalshi.com/getting_started/orderbook_responses',
  fees: 'https://kalshi.com/docs/kalshi-fee-schedule.pdf',
  rateLimits: 'https://docs.kalshi.com/getting_started/rate_limits',
  apiKeys: 'https://docs.kalshi.com/getting_started/api_keys',
  createOrderV2: 'https://docs.kalshi.com/api-reference/orders/create-order-v2',
  balance: 'https://docs.kalshi.com/api-reference/portfolio/get-balance',
  positions: 'https://docs.kalshi.com/api-reference/portfolio/get-positions',
  fills: 'https://docs.kalshi.com/api-reference/portfolio/get-fills',
  settlements: 'https://docs.kalshi.com/api-reference/portfolio/get-settlements',
  exchangeStatus: 'https://docs.kalshi.com/api-reference/exchange/get-exchange-status',
  quickstartWs: 'https://docs.kalshi.com/getting_started/quick_start_websockets',
  pagination: 'https://docs.kalshi.com/getting_started/pagination',
  fixedPoint: 'https://docs.kalshi.com/getting_started/fixed_point_migration',
  feeRounding: 'https://docs.kalshi.com/getting_started/fee_rounding',
};

export class KalshiError extends Error {
  constructor(message, { status, code, url } = {}) {
    super(message);
    this.name = 'KalshiError';
    this.status = status;
    this.code = code;
    this.url = url;
  }
}

/**
 * Refuse to talk to anything except an official Kalshi host. The demo/live
 * separation matters: demo credentials are not valid in production and this is
 * a demo-only project (docs: getting_started/api_environments).
 */
export function assertOfficialHost(url, { environment = 'demo' } = {}) {
  const allowed = environment === 'production' ? PRODUCTION_REST_ROOTS : DEMO_REST_ROOTS;
  const ok = allowed.some((root) => url === root || url.startsWith(root + '/') || url.startsWith(root + '?'));
  if (!ok) throw new KalshiError(`Refusing non-official or wrong-environment host: ${url}`, { url });
  return url;
}

export function createClient({
  root = DEFAULT_ROOT,
  fetchImpl = globalThis.fetch,
  timeoutMs = 20000,
  environment = 'demo',
  userAgent = 'Tradebot1-kalshi-dashboard',
  // Pacing and 429 handling. The demo API answers 429 to a burst of series reads
  // (observed 2026-11-22: 25 series failed in one cycle), so requests are spaced and
  // retried with backoff. Docs: https://docs.kalshi.com/getting_started/rate_limits
  minIntervalMs = 300,
  maxRetries = 3,
  baseBackoffMs = 750,
  sleepImpl = null,
  nowImpl = null,
} = {}) {
  if (typeof fetchImpl !== 'function') throw new Error('fetch is not available');
  assertOfficialHost(root, { environment });

  const sleep = sleepImpl ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const nowMs = nowImpl ?? (() => Date.now());
  let lastRequestAt = 0;
  let retries = 0;
  let throttledMs = 0;

  async function pace() {
    const wait = minIntervalMs - (nowMs() - lastRequestAt);
    if (wait > 0) {
      await sleep(wait);
      throttledMs += wait;
    }
    lastRequestAt = nowMs();
  }

  function backoffMs(res, attempt) {
    const header = res?.headers?.get?.('retry-after');
    const seconds = header == null ? NaN : Number(header);
    if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1000, 30000);
    return Math.min(baseBackoffMs * 2 ** attempt, 30000);
  }

  async function request(path, params = {}) {
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await requestOnce(path, params);
      } catch (err) {
        const retryable = err instanceof KalshiError && (err.status === 429 || err.status === 503);
        if (!retryable || attempt >= maxRetries) throw err;
        retries += 1;
        await sleep(backoffMs(err.response, attempt));
      }
    }
  }

  async function requestOnce(path, params = {}) {
    const url = new URL(root.replace(/\/$/, '') + path);
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue;
      url.searchParams.set(k, String(v));
    }
    const href = url.toString();
    assertOfficialHost(href, { environment });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res;
    await pace();
    try {
      res = await fetchImpl(href, {
        signal: controller.signal,
        headers: { accept: 'application/json', 'user-agent': userAgent },
      });
    } catch (err) {
      clearTimeout(timer);
      throw new KalshiError(`Network error for ${href}: ${err.message}`, { url: href });
    }
    clearTimeout(timer);
    const text = await res.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch { /* keep null */ }
    if (!res.ok) {
      const error = new KalshiError(`HTTP ${res.status} for ${href}${json?.error ? `: ${json.error.code ?? json.error.message ?? ''}` : ''}`, {
        status: res.status,
        code: json?.error?.code,
        url: href,
      });
      // Kept so the retry loop can honour a Retry-After header.
      error.response = res;
      throw error;
    }
    if (json === null && text) throw new KalshiError(`Non-JSON response for ${href}`, { url: href });
    return json ?? {};
  }

  /** Follow a cursor to the end, with a hard page cap so a bad cursor cannot loop. */
  async function paginate(path, params = {}, { maxPages = 12, key = null } = {}) {
    const out = {};
    let cursor;
    let pages = 0;
    do {
      const page = await request(path, { ...params, cursor });
      pages += 1;
      for (const [k, v] of Object.entries(page)) {
        if (k === 'cursor' || !Array.isArray(v)) continue;
        if (!out[k]) out[k] = [];
        out[k].push(...v);
      }
      cursor = page.cursor || undefined;
    } while (cursor && pages < maxPages);
    return { ...out, pages, complete: !cursor, lastCursor: cursor ?? '' };
  }

  return {
    root,
    request,
    paginate,
    /** Request-pacing statistics, reported with a cycle so the limits are visible. */
    stats: () => ({ retries, throttledMs, minIntervalMs }),
    exchangeStatus: () => request('/exchange/status'),
    listSeries: (params) => paginate('/series', params, { key: 'series' }),
    getSeries: (ticker) => request(`/series/${encodeURIComponent(ticker)}`),
    listEvents: (params) => paginate('/events', params, { key: 'events' }),
    getEvent: (ticker) => request(`/events/${encodeURIComponent(ticker)}`),
    listMarkets: (params) => paginate('/markets', params, { key: 'markets' }),
    getMarket: (ticker) => request(`/markets/${encodeURIComponent(ticker)}`),
    getOrderbook: (ticker) => request(`/markets/${encodeURIComponent(ticker)}/orderbook`),
    getTrades: (params) => paginate('/markets/trades', params, { key: 'trades' }),
    candlesticks: (seriesTicker, ticker, params) =>
      request(`/series/${encodeURIComponent(seriesTicker)}/markets/${encodeURIComponent(ticker)}/candlesticks`, params),
    balance: () => request('/portfolio/balance'),
    positions: (params) => paginate('/portfolio/positions', params, { key: 'market_positions' }),
    fills: (params) => paginate('/portfolio/fills', params, { key: 'fills' }),
    settlements: (params) => paginate('/portfolio/settlements', params, { key: 'settlements' }),
  };
}

/**
 * Normalise the order book into "contracts available at a price".
 *
 * Kalshi returns bids only, and a YES bid at X is a NO ask at (1 - X)
 * (docs: getting_started/orderbook_responses). The ladder below is therefore
 * derived, and labelled as derived wherever it is displayed.
 */
export function normaliseOrderbook(orderbook) {
  const ob = orderbook?.orderbook_fp ?? orderbook?.orderbook ?? {};
  const yes = normaliseLevels(ob.yes_dollars ?? ob.yes);
  const no = normaliseLevels(ob.no_dollars ?? ob.no);
  const yesAsk = no
    .map(([noPrice, qty]) => [round4(1 - noPrice), qty])
    .filter(([p]) => p >= 0 && p <= 1)
    .sort((a, b) => a[0] - b[0]);
  const noAsk = yes
    .map(([yesPrice, qty]) => [round4(1 - yesPrice), qty])
    .filter(([p]) => p >= 0 && p <= 1)
    .sort((a, b) => a[0] - b[0]);
  const bestYesBid = yes.length ? Math.max(...yes.map(([p]) => p)) : null;
  const bestYesAsk = yesAsk.length ? yesAsk[0][0] : null;
  const yesDepthContracts = yes.reduce((s, [, q]) => s + q, 0);
  const yesAskDepthContracts = yesAsk.reduce((s, [, q]) => s + q, 0);
  return {
    yesBids: yes.sort((a, b) => b[0] - a[0]),
    noBids: no.sort((a, b) => b[0] - a[0]),
    yesAsks: yesAsk,
    noAsks: noAsk,
    bestYesBid,
    bestYesAsk,
    bestNoBid: no.length ? Math.max(...no.map(([p]) => p)) : null,
    bestNoAsk: noAsk.length ? noAsk[0][0] : null,
    spread: bestYesBid != null && bestYesAsk != null ? round4(bestYesAsk - bestYesBid) : null,
    yesBidDepthContracts: round2(yesDepthContracts),
    yesAskDepthContracts: round2(yesAskDepthContracts),
    // Dollar notional resting on each side, using the price of each level.
    yesBidDepthDollars: round2(yes.reduce((s, [p, q]) => s + p * q, 0)),
    yesAskDepthDollars: round2(yesAsk.reduce((s, [p, q]) => s + p * q, 0)),
    derivedAt: new Date().toISOString(),
    source: SOURCES.orderbook,
    semanticsSource: SOURCES.orderbookSemantics,
  };
}

function normaliseLevels(levels) {
  if (!Array.isArray(levels)) return [];
  return levels
    .map((entry) => {
      if (Array.isArray(entry)) return [Number(entry[0]), Number(entry[1])];
      if (entry && typeof entry === 'object') return [Number(entry.price ?? entry.p), Number(entry.quantity ?? entry.q ?? entry.count)];
      return null;
    })
    .filter((pair) => pair && Number.isFinite(pair[0]) && Number.isFinite(pair[1]) && pair[1] > 0)
    .map(([p, q]) => [round4(p), round2(q)]);
}

export function round2(n) { return Math.round(n * 100) / 100; }
export function round4(n) { return Math.round(n * 10000) / 10000; }
