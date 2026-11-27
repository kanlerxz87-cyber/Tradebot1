#!/usr/bin/env node
/* tools/terminal-collect.mjs — server-side swing log for the /terminal/ dashboard.
 *
 * Why this exists
 * ---------------
 * The terminal reads Kalshi in the visitor's browser, which is what makes it live.
 * It has one unavoidable limitation: a browser session only sees the market while
 * the tab is open, so the ≥ $0.10 alert chat starts empty for every visitor and every
 * refresh. This collector closes that gap the same way the board's collector does:
 * it samples the demo API on a schedule, from a host that can reach it, and commits
 * the swings it measures to terminal/data/alerts.json. The dashboard merges that log
 * (labelled "server-observed") with its own live feed (labelled "this session").
 *
 * What it does NOT do
 * -------------------
 *  * It never writes a price it did not read, and never carries a price forward to
 *    manufacture a move. A market with no price in this sample is skipped.
 *  * It never compares across a gap it cannot attribute: if the previous sample of a
 *    market is older than MAX_GAP_SECONDS, that market is rebased, not alerted.
 *  * It never uses a production endpoint. The base URL is hard-coded to the demo root
 *    the brief specifies and an environment variable cannot override it.
 *
 * Official endpoints used (public, no authentication):
 *   GET /events?status=open&with_nested_markets=true
 *     https://docs.kalshi.com/api-reference/events/get-events
 *   GET /markets?event_ticker=…            (fallback when nesting is not returned)
 *     https://docs.kalshi.com/api-reference/market/get-markets
 *
 * Usage
 *   node tools/terminal-collect.mjs            # collect, write terminal/data/*
 *   node tools/terminal-collect.mjs --dry-run  # collect, write nothing
 *   node tools/terminal-collect.mjs --self-test # exercise the rules offline
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const OUT_DIR = path.join(ROOT, 'terminal/data');
const ALERTS_FILE = path.join(OUT_DIR, 'alerts.json');
const SNAPSHOT_FILE = path.join(OUT_DIR, 'snapshot.json');

/* The demo root, hard-coded. See docs.kalshi.com/getting_started/api_environments. */
const DEMO_ROOT = 'https://external-api.demo.kalshi.co/trade-api/v2';
const MAX_GAP_SECONDS = 45 * 60;      // two scheduled samples + slack
const THRESHOLD = 0.10;               // dollars, inclusive
const MAX_ALERTS = 500;               // ring buffer
const MAX_MARKETS = 4000;
const PAGE_LIMIT = 200;
const MAX_PAGES = 12;
const PACING_MS = 150;                // the public read budget is generous; be polite

/* ---------- pure rules (also covered by tools/terminal-collect.test.mjs) ---------- */

const num = (v) => {
  if (v == null || v === '') return null;
  const n = typeof v === 'number' ? v : parseFloat(v);
  return Number.isFinite(n) ? n : null;
};

/* Same measurement rule as the browser: last trade first, then quote midpoint.
   Never the bid alone, never a default. */
export function priceOf(market) {
  const last = num(market.last_price_dollars) ?? (num(market.last_price) != null ? market.last_price / 100 : null);
  if (last != null) return { price: last, basis: 'last_trade' };
  const bid = num(market.yes_bid_dollars) ?? (num(market.yes_bid) != null ? market.yes_bid / 100 : null);
  const ask = num(market.yes_ask_dollars) ?? (num(market.yes_ask) != null ? market.yes_ask / 100 : null);
  if (bid != null && ask != null && !(bid <= 0 && ask >= 1) && ask >= bid) {
    return { price: Number(((bid + ask) / 2).toFixed(4)), basis: 'quote_mid' };
  }
  return { price: null, basis: 'unpriced' };
}

/* Topic assignment by the exchange's own fields, identical in order and outcome to
   terminal/assets/js/topics.js (which is tested separately). Duplicated on purpose:
   the collector must not depend on a browser bundle. */
const RULES = [
  { id: 'gas', seriesPrefixes: ['kxaaagas'], tags: ['oil and energy', 'oil & gas', 'gas', 'gasoline'], categories: [] },
  { id: 'elections', seriesPrefixes: [], tags: ['us elections', 'senate', 'house', 'governor', 'presidential'], categories: ['elections'] },
  { id: 'culture', seriesPrefixes: [], tags: ['music', 'awards', 'television', 'movies', 'celebrities'], categories: ['entertainment'] },
  { id: 'crypto', seriesPrefixes: [], tags: ['crypto', 'bitcoin', 'btc', 'ethereum', 'eth'], categories: ['crypto'] },
  { id: 'golf', seriesPrefixes: ['kxpgatour', 'kxdptour', 'kxlpga'], tags: ['golf', 'pga', 'lpga', 'dp world tour', 'liv golf'], categories: [] },
];
const TITLE_KEYWORDS = {
  gas: ['gas price', 'gasoline', 'aaa gas', 'pump price', 'fuel price', 'diesel price', 'natural gas'],
  elections: ['election', 'presidential nominee', 'senate', 'governor', 'electoral', 'midterm', 'ballot'],
  culture: ['oscar', 'grammy', 'emmy', 'golden globe', 'box office', 'album', 'billboard', 'rotten tomatoes', 'game of the year'],
  crypto: ['bitcoin', 'ethereum', 'solana', 'dogecoin', 'xrp', 'stablecoin', 'crypto'],
  golf: ['pga', 'lpga', 'masters', 'ryder cup', 'presidents cup', 'open championship', 'fedex cup', 'birdie', 'hole in one'],
};

export function classify({ seriesTicker, tags = [], category, title = '' }) {
  const series = String(seriesTicker || '').toLowerCase();
  const tagSet = tags.map((t) => String(t).toLowerCase());
  const cat = String(category || '').toLowerCase();
  for (const r of RULES) for (const p of r.seriesPrefixes) if (series.startsWith(p)) return { topic: r.id, evidence: `series ${series.toUpperCase()}` };
  for (const r of RULES) for (const t of r.tags) if (tagSet.includes(t)) return { topic: r.id, evidence: `tag "${t}"` };
  for (const r of RULES) for (const c of r.categories) if (cat === c) return { topic: r.id, evidence: `category "${category}"` };
  const hay = ' ' + String(title).toLowerCase() + ' ';
  for (const r of RULES) {
    if (TITLE_KEYWORDS[r.id].some((k) => hay.includes(k))) return { topic: r.id, evidence: 'title keywords' };
  }
  return { topic: null, evidence: 'out of scope' };
}

/* Compare one market's current price with the previous sample.
   Returns an alert object, or null. `prev` is {price, ts, basis} from the last run. */
export function detectSwing({ ticker, title, topic, price, basis, now, prev, sourceUrl }) {
  if (price == null || prev == null || prev.price == null) return null;
  if (!(now > prev.ts)) return null;                       // clock went backwards or same run
  if (now - prev.ts > MAX_GAP_SECONDS) return null;        // rebase, do not compare across the gap
  const delta = Number((price - prev.price).toFixed(4));
  const abs = Math.abs(delta);
  if (abs < THRESHOLD - 1e-9) return null;
  return {
    id: `${ticker}_${prev.ts}_${now}`,
    ticker, title, topic,
    direction: delta > 0 ? 'up' : 'down',
    from_price: prev.price,
    to_price: price,
    from_ts: prev.ts,
    to_ts: now,
    from_iso: new Date(prev.ts * 1000).toISOString(),
    to_iso: new Date(now * 1000).toISOString(),
    abs_delta: abs,
    basis,
    source_url: sourceUrl,
  };
}

export function mergeAlerts(existing, incoming, cap = MAX_ALERTS) {
  const byId = new Map();
  for (const a of [...(existing || []), ...(incoming || [])]) {
    if (!a || !a.id || !a.ticker) continue;
    if (!(Number(a.abs_delta) >= THRESHOLD - 1e-9)) continue;
    byId.set(a.id, a);
  }
  return [...byId.values()].sort((a, b) => b.to_ts - a.to_ts).slice(0, cap);
}

/* ---------- network ---------- */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getJson(url, timeoutMs = 20000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { accept: 'application/json' } });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    return { ok: res.ok, status: res.status, data, text: res.ok ? null : text.slice(0, 300) };
  } catch (err) {
    return { ok: false, status: 0, data: null, error: String(err && err.message || err) };
  } finally {
    clearTimeout(t);
  }
}

async function fetchEvents(status = 'open') {
  const events = [];
  let cursor = null, pages = 0, lastCursor = null, errors = [];
  while (pages < MAX_PAGES) {
    const url = new URL(`${DEMO_ROOT}/events`);
    url.searchParams.set('status', status);
    url.searchParams.set('limit', String(PAGE_LIMIT));
    url.searchParams.set('with_nested_markets', 'true');
    if (cursor) url.searchParams.set('cursor', cursor);
    const res = await getJson(url);
    if (!res.ok) { errors.push(`events?status=${status} → HTTP ${res.status} ${res.error || res.text || ''}`.trim()); break; }
    const batch = (res.data && res.data.events) || [];
    events.push(...batch);
    pages += 1;
    const next = res.data && res.data.cursor;
    if (!next || next === lastCursor || batch.length === 0) break;
    lastCursor = cursor;
    cursor = next;
    await sleep(PACING_MS);
  }
  return { events, pages, errors };
}

/* ---------- main ---------- */
async function collect({ dryRun = false } = {}) {
  const startedAt = Math.floor(Date.now() / 1000);
  const errors = [];
  const previous = (() => {
    try { return JSON.parse(readFileSyncSafe(ALERTS_FILE)) || {}; } catch { return {}; }
  })();

  const open = await fetchEvents('open');
  errors.push(...open.errors);
  const settled = await fetchEvents('settled');
  errors.push(...settled.errors);

  const lastPrices = (previous && previous.last_prices) || {};
  const alerts = [];
  const rows = [];
  const nextPrices = {};

  for (const ev of [...open.events, ...settled.events]) {
    for (const m of ev.markets || []) {
      if (!m || !m.ticker) continue;
      const { price, basis } = priceOf(m);
      const cls = classify({
        seriesTicker: m.series_ticker || ev.series_ticker,
        tags: m.tags || [],
        category: m.category || ev.category,
        title: m.title || ev.title,
      });
      if (price != null) nextPrices[m.ticker] = { price, ts: startedAt, basis };
      if (!cls.topic) continue;
      const prev = lastPrices[m.ticker];
      const alert = detectSwing({
        ticker: m.ticker,
        title: m.title || ev.title || m.ticker,
        topic: cls.topic,
        price, basis, now: startedAt, prev,
        sourceUrl: `${DEMO_ROOT}/markets/${encodeURIComponent(m.ticker)}`,
      });
      if (alert) alerts.push(alert);
      if (price != null) {
        rows.push({
          ticker: m.ticker,
          event_ticker: m.event_ticker || ev.event_ticker || null,
          series_ticker: m.series_ticker || ev.series_ticker || null,
          title: m.title || ev.title || m.ticker,
          topic: cls.topic,
          topic_evidence: cls.evidence,
          status: m.status || ev.status || null,
          result: ['yes', 'no'].includes(String(m.result || '').toLowerCase()) ? String(m.result).toLowerCase() : null,
          close_time: m.close_time || ev.close_time || null,
          price, price_basis: basis,
          previous_price: num(m.previous_price_dollars),
          yes_bid: num(m.yes_bid_dollars),
          yes_ask: num(m.yes_ask_dollars),
          volume_24h: num(m.volume_24h_fp),
          open_interest: num(m.open_interest_fp),
          source_url: `${DEMO_ROOT}/markets/${encodeURIComponent(m.ticker)}`,
        });
      }
    }
  }

  /* Keep the last price map bounded: most recently seen markets win. */
  const trimmedPrices = Object.fromEntries(
    Object.entries(nextPrices)
      .sort((a, b) => b[1].ts - a[1].ts)
      .slice(0, MAX_MARKETS),
  );
  const merged = mergeAlerts(previous.alerts || [], alerts);
  const doc = {
    schema: 'terminal-alerts/1',
    generated_at: new Date(startedAt * 1000).toISOString(),
    generated_ts: startedAt,
    source: {
      rest_root: DEMO_ROOT,
      endpoint: 'GET /events?status=open|settled&with_nested_markets=true',
      docs: 'https://docs.kalshi.com/api-reference/events/get-events',
    },
    rule: {
      threshold_dollars: THRESHOLD,
      price_basis: 'last trade, else bid/ask midpoint; never the bid alone',
      gap_seconds: MAX_GAP_SECONDS,
      note: 'A swing is the same market observed at two times at least $0.10 apart. Markets with no price in a sample are skipped, and a market whose previous sample is older than gap_seconds is rebased instead of compared.',
    },
    counts: {
      events_open: open.events.length,
      events_settled: settled.events.length,
      markets_with_price: Object.keys(nextPrices).length,
      markets_in_focus: rows.length,
      new_alerts_this_run: alerts.length,
      alerts_total: merged.length,
    },
    errors,
    alerts: merged,
    last_prices: trimmedPrices,
  };

  const snapshot = {
    schema: 'terminal-snapshot/1',
    generated_at: doc.generated_at,
    generated_ts: startedAt,
    source: doc.source,
    counts: doc.counts,
    errors,
    markets: rows.sort((a, b) => (b.volume_24h || 0) - (a.volume_24h || 0)).slice(0, 600),
  };

  /* Fail closed: a run that reached no event at all writes nothing, so a network
     outage on the runner cannot replace a good published log with an empty one. */
  const wroteNothing = open.events.length === 0 && settled.events.length === 0;
  if (!dryRun && wroteNothing) {
    return { doc, snapshot, wroteNothing };
  }
  if (!dryRun) {
    await mkdir(OUT_DIR, { recursive: true });
    await writeFile(ALERTS_FILE, JSON.stringify(doc, null, 1) + '\n', 'utf8');
    await writeFile(SNAPSHOT_FILE, JSON.stringify(snapshot, null, 1) + '\n', 'utf8');
  }
  return { doc, snapshot };
}

function readFileSyncSafe(p) {
  try { return readFileSync(p, 'utf8'); } catch { return null; }
}

export { collect, DEMO_ROOT, THRESHOLD, DEMO_ROOT as ROOT_URL };

/* ---------- CLI ---------- */
const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);
if (isMain) {
  const dryRun = process.argv.includes('--dry-run');
  try {
    const { doc, wroteNothing } = await collect({ dryRun });
    console.log(`events open=${doc.counts.events_open} settled=${doc.counts.events_settled} ` +
      `priced=${doc.counts.markets_with_price} in-focus=${doc.counts.markets_in_focus} ` +
      `new-alerts=${doc.counts.new_alerts_this_run} total=${doc.counts.alerts_total}`);
    for (const e of doc.errors) console.log(`warning: ${e}`);
    if (dryRun) console.log('dry run: nothing written');
    if (wroteNothing) {
      console.error('::error::no events were read from the demo API; refusing to overwrite the published log');
      process.exit(2);
    }
  } catch (err) {
    console.error('collector failed:', err && err.stack || err);
    process.exit(1);
  }
}
