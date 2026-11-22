#!/usr/bin/env node
/**
 * Capture verified public Kalshi demo data for the live console.
 *
 * Design rules, all from docs/live/data/sources.json:
 *
 *  * Official host only. The base URL is a constant and is never read from the environment, so a
 *    stray variable cannot point the tool at production (S1).
 *  * Every value written carries the exact request URL that produced it and the time it was read
 *    (S17-S25 provenance rule). No field is computed from another field unless the derivation is
 *    recorded in `derived`.
 *  * Nothing is invented. A failed request produces an `errors[]` entry and an empty list; the file
 *    still records what succeeded. A previous file is never overwritten with worse data unless the
 *    new run has fewer than `--min-markets` markets, in which case the run fails and leaves the old
 *    file alone.
 *  * Cursors are bounded (S7) so the job is a fixed, predictable number of requests.
 *
 * Usage:
 *   node docs/live/tools/capture.mjs               # write docs/live/data/live.json
 *   node docs/live/tools/capture.mjs --dry-run     # print a summary, write nothing
 *   node docs/live/tools/capture.mjs --out FILE
 */

import { writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TOPIC_RULES, routeSeries, quoteOf, bookOf } from '../assets/core.mjs';

const BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_OUT = path.join(HERE, '..', 'data', 'live.json');

const LIMITS = {
  eventPages: 6, // x 200 events = 1200 events scanned (S7)
  marketsPerEvent: 40,
  seriesPages: 3,
  books: 40, // order books fetched for the highest-dollar markets
  minMarkets: 25, // a thinner run is treated as a failure, not as new truth
  timeoutMs: 25_000,
  pauseMs: 120,
};

const args = process.argv.slice(2);
const flag = (name) => args.includes(`--${name}`);
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};
const OUT = path.resolve(value('out', DEFAULT_OUT));
const DRY = flag('dry-run');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const nowIso = () => new Date().toISOString();

/** One recorded request. Returns {ok, status, url, data, error, ms}. */
export async function get(pathname, params = {}, label = pathname) {
  const query = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  );
  const url = `${BASE}${pathname}${query.size ? `?${query}` : ''}`;
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), LIMITS.timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { accept: 'application/json', 'user-agent': 'tradebot1-live-capture/1.0 (+public reads only)' },
    });
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    return {
      label,
      ok: response.ok && data !== null,
      status: response.status,
      url,
      read_at: nowIso(),
      ms: Date.now() - started,
      rate_limit: {
        limit: response.headers.get('x-ratelimit-limit'),
        remaining: response.headers.get('x-ratelimit-remaining'),
        cost: response.headers.get('x-ratelimit-cost'),
      },
      data,
      error: response.ok && data !== null ? null : `HTTP ${response.status}`,
    };
  } catch (error) {
    return {
      label,
      ok: false,
      status: 0,
      url,
      read_at: nowIso(),
      ms: Date.now() - started,
      data: null,
      error: `${error.name}: ${error.message}`,
    };
  } finally {
    clearTimeout(timer);
  }
}

const log = [];
const errors = [];
function record(result) {
  log.push({
    label: result.label,
    url: result.url,
    status: result.status,
    ok: result.ok,
    ms: result.ms,
    read_at: result.read_at,
    error: result.error,
  });
  if (!result.ok) errors.push({ label: result.label, url: result.url, status: result.status, error: result.error });
  return result;
}

/* ------------------------------------------------------------------ discovery */

export async function seriesFor(topicRule) {
  const found = new Map();
  for (const selector of topicRule.selectors) {
    let cursor = '';
    for (let page = 0; page < LIMITS.seriesPages; page += 1) {
      const result = record(
        await get('/series', { [selector.param]: selector.value, limit: 200, cursor }, `series ${selector.param}=${selector.value} page ${page + 1}`),
      );
      if (!result.ok) break;
      for (const series of result.data?.series ?? []) {
        const route = routeSeries(series, topicRule.topic);
        // The selector already proved membership; keep the official selector as the evidence even
        // when routeSeries fell through to a keyword, so the row cannot claim more than it knows.
        if (!found.has(series.ticker)) {
          found.set(series.ticker, {
            ticker: series.ticker,
            title: series.title ?? null,
            category: series.category ?? null,
            categories: Array.isArray(series.categories) ? series.categories : [],
            tags: Array.isArray(series.tags) ? series.tags : [],
            settlement_sources: Array.isArray(series.settlement_sources) ? series.settlement_sources : [],
            routed_by: `official selector ${selector.param}="${selector.value}"`,
            routed_official: true,
            derived: Boolean(topicRule.derived),
            selector_url: result.url,
          });
        }
        void route;
      }
      cursor = result.data?.cursor ?? '';
      if (!cursor) break;
      await sleep(LIMITS.pauseMs);
    }
  }
  return found;
}

/**
 * One bounded scan of open events with nested markets (S19), then attach each market to every
 * topic whose series it belongs to. An event is kept only if at least one of its markets does.
 */
export async function scanEvents(seriesByTopic) {
  const byTicker = new Map();
  for (const [topic, series] of Object.entries(seriesByTopic)) {
    for (const ticker of series.keys()) byTicker.set(ticker, topic);
  }
  const events = new Map();
  let cursor = '';
  let pages = 0;
  for (let page = 0; page < LIMITS.eventPages; page += 1) {
    const result = record(await get('/events', { status: 'open', with_nested_markets: 'true', limit: 200, cursor }, `events page ${page + 1}`));
    if (!result.ok) break;
    pages += 1;
    for (const event of result.data?.events ?? []) {
      const topic = byTicker.get(event.series_ticker);
      if (!topic) continue;
      const markets = (Array.isArray(event.markets) ? event.markets : []).slice(0, LIMITS.marketsPerEvent).map((market) => ({
        ticker: market.ticker,
        event_ticker: event.event_ticker,
        series_ticker: event.series_ticker,
        topic,
        title: market.title ?? event.title ?? null,
        yes_sub_title: market.yes_sub_title ?? null,
        status: market.status ?? null,
        result: market.result ?? '',
        close_time: market.close_time ?? null,
        expected_expiration_time: market.expected_expiration_time ?? null,
        last_price_dollars: market.last_price_dollars ?? null,
        yes_bid_dollars: market.yes_bid_dollars ?? null,
        yes_ask_dollars: market.yes_ask_dollars ?? null,
        no_bid_dollars: market.no_bid_dollars ?? null,
        no_ask_dollars: market.no_ask_dollars ?? null,
        yes_bid_size_fp: market.yes_bid_size_fp ?? null,
        yes_ask_size_fp: market.yes_ask_size_fp ?? null,
        volume_fp: market.volume_fp ?? null,
        volume_24h_fp: market.volume_24h_fp ?? null,
        open_interest_fp: market.open_interest_fp ?? null,
        settlement_value_dollars: market.settlement_value_dollars ?? null,
        settlement_ts: market.settlement_ts ?? null,
        source_url: result.url,
        read_at: result.read_at,
      }));
      if (!markets.length) continue;
      events.set(event.event_ticker, {
        event_ticker: event.event_ticker,
        series_ticker: event.series_ticker,
        topic,
        title: event.title ?? null,
        sub_title: event.sub_title ?? null,
        settlement_sources: Array.isArray(event.settlement_sources) ? event.settlement_sources : [],
        markets,
        source_url: result.url,
        read_at: result.read_at,
      });
    }
    cursor = result.data?.cursor ?? '';
    if (!cursor) break;
    await sleep(LIMITS.pauseMs);
  }
  return { events: [...events.values()], pages };
}

/**
 * Resolutions: settled events, so the console can show how an event actually resolved (S8/S9).
 * Only markets whose `result` is already yes/no/scalar are reported as resolved.
 */
export async function scanResolutions(seriesByTopic) {
  const byTicker = new Map();
  for (const [topic, series] of Object.entries(seriesByTopic)) {
    for (const ticker of series.keys()) byTicker.set(ticker, topic);
  }
  const resolved = [];
  let cursor = '';
  for (let page = 0; page < 2; page += 1) {
    const result = record(await get('/events', { status: 'settled', with_nested_markets: 'true', limit: 200, cursor }, `settled events page ${page + 1}`));
    if (!result.ok) break;
    for (const event of result.data?.events ?? []) {
      const topic = byTicker.get(event.series_ticker);
      if (!topic) continue;
      for (const market of Array.isArray(event.markets) ? event.markets : []) {
        const verdict = String(market.result ?? '').trim().toLowerCase();
        if (verdict !== 'yes' && verdict !== 'no' && verdict !== 'scalar') continue;
        resolved.push({
          event_ticker: event.event_ticker,
          series_ticker: event.series_ticker,
          topic,
          event_title: event.title ?? null,
          market_title: market.title ?? null,
          ticker: market.ticker,
          result: verdict,
          status: market.status ?? null,
          settlement_value_dollars: market.settlement_value_dollars ?? null,
          settlement_ts: market.settlement_ts ?? null,
          close_time: market.close_time ?? null,
          settlement_sources: Array.isArray(event.settlement_sources) ? event.settlement_sources : [],
          source_url: result.url,
          read_at: result.read_at,
        });
      }
    }
    cursor = result.data?.cursor ?? '';
    if (!cursor) break;
    await sleep(LIMITS.pauseMs);
  }
  return resolved;
}

/** Order books for the markets carrying the most recent dollar volume (S4). */
export async function enrichBooks(markets) {
  const ranked = [...markets]
    .filter((market) => market.status === 'active')
    .sort((a, b) => {
      const dollars = (m) => (Number(m.last_price_dollars) || 0) * (Number(m.volume_24h_fp) || 0);
      return dollars(b) - dollars(a);
    })
    .slice(0, LIMITS.books);
  const books = {};
  for (const market of ranked) {
    const result = record(await get(`/markets/${encodeURIComponent(market.ticker)}/orderbook`, { depth: 10 }, `orderbook ${market.ticker}`));
    if (!result.ok) continue;
    const parsed = bookOf(result.data?.orderbook_fp);
    books[market.ticker] = {
      ...parsed,
      source_url: result.url,
      read_at: result.read_at,
    };
    await sleep(LIMITS.pauseMs);
  }
  return books;
}

/* ---------------------------------------------------------------------- main */

export async function capture() {
  const startedAt = nowIso();
  const status = record(await get('/exchange/status', {}, 'exchange status'));
  const seriesByTopic = {};
  for (const rule of TOPIC_RULES) {
    seriesByTopic[rule.topic] = await seriesFor(rule);
  }
  const scan = await scanEvents(seriesByTopic);
  const allMarkets = scan.events.flatMap((event) => event.markets);
  const books = await enrichBooks(allMarkets);
  const resolutions = await scanResolutions(seriesByTopic);

  const topics = TOPIC_RULES.map((rule) => {
    const series = seriesByTopic[rule.topic];
    const events = scan.events.filter((event) => event.topic === rule.topic);
    return {
      topic: rule.topic,
      label: rule.label,
      official_selector: rule.official,
      note: rule.note,
      derived: Boolean(rule.derived),
      series: [...series.values()],
      event_count: events.length,
      market_count: events.reduce((total, event) => total + event.markets.length, 0),
    };
  });

  const generated = nowIso();
  const output = {
    version: 1,
    environment: 'demo',
    base_url: BASE,
    root_source: 'https://docs.kalshi.com/getting_started/api_environments',
    generated_at: generated,
    started_at: startedAt,
    exchange: status.ok
      ? {
          exchange_active: status.data?.exchange_active ?? null,
          trading_active: status.data?.trading_active ?? null,
          index_statuses: status.data?.exchange_index_statuses ?? [],
          source_url: status.url,
          read_at: status.read_at,
        }
      : null,
    coverage: {
      event_pages_scanned: scan.pages,
      events_carried: scan.events.length,
      markets_carried: allMarkets.length,
      books_fetched: Object.keys(books).length,
      resolutions_carried: resolutions.length,
      requests: log.length,
      partial: scan.pages >= LIMITS.eventPages,
      note: 'Bounded scan of the demo catalogue, not a complete exchange ranking. Every row keeps the URL and time it was read.',
    },
    topics,
    events: scan.events,
    books,
    resolutions,
    errors,
    requests: log,
  };

  if (DRY) {
    console.log(JSON.stringify({ ...output, events: `${output.events.length} events`, requests: log.length, errors }, null, 2));
    return;
  }

  if (allMarkets.length < LIMITS.minMarkets) {
    // Refuse to replace a good file with a thin one: report and exit non-zero for the workflow.
    console.error(`refusing to write: only ${allMarkets.length} markets (< ${LIMITS.minMarkets}); previous file left untouched`);
    console.error(JSON.stringify(errors, null, 2));
    process.exitCode = 1;
    return;
  }

  try {
    JSON.parse(await readFile(OUT, 'utf8'));
  } catch {
    /* no previous file, that is fine */
  }
  await writeFile(OUT, `${JSON.stringify(output, null, 2)}\n`);
  console.log(
    `wrote ${path.relative(process.cwd(), OUT)}: ${output.events.length} events, ${allMarkets.length} markets, ` +
      `${Object.keys(books).length} books, ${resolutions.length} resolutions, ${log.length} requests, ${errors.length} errors`,
  );
}

// Only run when invoked directly, so the module can be imported by the check script with a
// stubbed `fetch` and prove that every request it issues targets the official demo host.
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  capture().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
