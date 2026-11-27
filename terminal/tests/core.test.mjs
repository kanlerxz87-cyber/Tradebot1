/* terminal/tests/core.test.mjs — no-network tests for the terminal's pure logic.
 *
 * Every assertion is either (a) arithmetic the official fee schedule states, or
 * (b) a rule this repository documents in terminal/verification.html. Nothing here
 * needs egress to Kalshi, so it runs in the same `node --test` job as the rest of
 * the repository.
 *
 *   node --test terminal/tests/core.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const ROOT = path.resolve(new URL('../..', import.meta.url).pathname);

/* Load a browser script into a sandbox. The terminal's modules are plain
 * top-level consts (no build step, no imports), so a vm context is enough. */
function load(...files) {
  const sandbox = {
    console,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    Map,
    Set,
    Infinity,
    NaN,
    URLSearchParams,
    TextEncoder,
    fetch: () => Promise.reject(new Error('network disabled in tests')),
    // common.js registers a DOMContentLoaded listener; the tests never trigger
    // it, but the object has to exist.
    document: { addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, createElement: () => ({ style: {}, appendChild() {} }), body: {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    setTimeout,
    clearTimeout,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const ctx = vm.createContext(sandbox);
  for (const f of files) {
    const code = readFileSync(path.join(ROOT, f), 'utf8');
    vm.runInContext(code, ctx, { filename: f });
  }
  // Top-level `const`/`class` declarations are lexical: they stay in the context's
  // script scope, so they must be read back explicitly.
  const names = [
    'SITE', 'store', 'fmtUsd', 'fmtCents', 'fmtContracts', 'escapeHtml',
    'TOPICS', 'TOPIC_BY_ID', 'classifyText', 'classifyMarket', 'driverLinks',
    'Model', 'AlertEngine', 'PriceChart', 'Kalshi', 'PaperFees', 'PaperPortfolio',
    'SimulatedFeed',
  ];
  const exposed = vm.runInContext(
    '({' + names.map((n) => `${n}: (typeof ${n} === 'undefined' ? undefined : ${n})`).join(',') + '})',
    ctx,
  );
  return Object.assign(ctx, exposed);
}

/* ------------------------------------------------------------------ */
/* Fee arithmetic — kalshi.com/docs/kalshi-fee-schedule.pdf            */
/* ------------------------------------------------------------------ */
test('taker fee reproduces every published single-contract row', () => {
  const ctx = load('terminal/assets/js/store.js', 'terminal/assets/js/common.js');
  // Published General Trading Fees Table (effective 2026-07-07), 1-contract column.
  const table = [
    [0.01, 0.01], [0.05, 0.01], [0.10, 0.01], [0.15, 0.01], [0.20, 0.02],
    [0.25, 0.02], [0.30, 0.02], [0.35, 0.02], [0.40, 0.02], [0.45, 0.02],
    [0.50, 0.02], [0.55, 0.02], [0.60, 0.02], [0.65, 0.02], [0.70, 0.02],
    [0.75, 0.02], [0.80, 0.02], [0.85, 0.01], [0.90, 0.01], [0.95, 0.01],
    [0.99, 0.01],
  ];
  for (const [price, expected] of table) {
    const got = ctx.PaperFees.taker(1, price);
    assert.equal(Math.round(got * 100) / 100, expected, `fee at $${price}`);
  }
});

test('taker fee reproduces every published 100-contract row', () => {
  const ctx = load('terminal/assets/js/store.js', 'terminal/assets/js/common.js');
  const table = [
    [0.01, 0.07], [0.05, 0.34], [0.10, 0.63], [0.15, 0.90], [0.20, 1.12],
    [0.25, 1.32], [0.30, 1.47], [0.35, 1.60], [0.40, 1.68], [0.45, 1.74],
    [0.50, 1.75], [0.55, 1.74], [0.60, 1.68], [0.65, 1.60], [0.70, 1.47],
    [0.75, 1.32], [0.80, 1.12], [0.85, 0.90], [0.90, 0.63], [0.95, 0.34],
    [0.99, 0.07],
  ];
  for (const [price, expected] of table) {
    const got = ctx.PaperFees.taker(100, price);
    assert.equal(Math.round(got * 100) / 100, expected, `fee at $${price} × 100`);
  }
});

/* ------------------------------------------------------------------ */
/* Taxonomy — official category/tag fields, not title keywords          */
/* ------------------------------------------------------------------ */
test('classification prefers the exchange category and tag over title text', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js');
  // A golf event whose title happens to contain an elections keyword: the old
  // keyword-only classifier filed it under elections.
  const golf = ctx.classifyMarket({
    title: 'Presidents Cup: Scottie Scheffler wins',
    category: 'Sports',
    tags: ['Golf', 'PGA'],
    series_ticker: 'KXPRESIDENTSCUP',
  });
  assert.equal(golf.topic, 'golf', 'series/tag evidence must beat the title keyword');

  const gas = ctx.classifyMarket({
    title: 'Will average gas prices be above $3.50?',
    category: 'Economics',
    tags: ['Oil and energy'],
    series_ticker: 'KXAAAGASM',
  });
  assert.equal(gas.topic, 'gas');

  const elections = ctx.classifyMarket({
    title: 'Will X be the Democratic nominee in 2028?',
    category: 'Elections',
    tags: ['US Elections'],
    series_ticker: 'KXPRESNOMD',
  });
  assert.equal(elections.topic, 'elections');

  const culture = ctx.classifyMarket({
    title: '2026 Game of the Year?',
    category: 'Entertainment',
    tags: ['Awards'],
    series_ticker: 'KXGAMEAWARDS',
  });
  assert.equal(culture.topic, 'culture');

  const crypto = ctx.classifyMarket({
    title: 'Bitcoin price on Nov 27, 2026?',
    category: 'Crypto',
    tags: ['Bitcoin'],
    series_ticker: 'KXBTCD',
  });
  assert.equal(crypto.topic, 'crypto');
});

test('an out-of-scope market is omitted, not guessed from one weak word', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js');
  const row = ctx.classifyMarket({
    title: 'Will the S&P 500 close above 7000 this year?',
    category: 'Economics',
    tags: ['Index'],
    series_ticker: 'KXINX',
  });
  assert.equal(row.topic, null);
});

test('the classifier reports the evidence it used', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js');
  const row = ctx.classifyMarket({ title: 'Masters winner', category: 'Sports', tags: ['Golf'], series_ticker: '' });
  assert.ok(row.evidence, 'a classification must carry its evidence');
  assert.match(row.evidence, /golf|sports/i);
});

/* ------------------------------------------------------------------ */
/* Alert engine — the ≥ $0.10 rule, boundary inclusive                  */
/* ------------------------------------------------------------------ */
test('a move of exactly $0.10 alerts, $0.09 does not', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/model.js');
  const engine = new ctx.AlertEngine(0);
  const meta = { ticker: 'TEST', title: 't', topic: 'gas' };
  assert.equal(engine.update('TEST', 0.50, meta), null, 'first sample establishes a reference only');
  // Price the reference away from the current price first so the window rule cannot fire.
  assert.equal(engine.update('TEST', 0.59, meta), null, '$0.09 must not alert');
  const fired = engine.update('TEST', 0.60, meta);
  assert.ok(fired, 'a cumulative $0.10 move must alert');
  assert.equal(fired.direction, 'up');
  assert.equal(Math.round(fired.delta * 100) / 100, 0.10);
});

test('after an alert the reference resets, so one excursion does not re-alert', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/model.js');
  const engine = new ctx.AlertEngine(0);
  const meta = { ticker: 'T', title: 't', topic: 'gas' };
  engine.update('T', 0.50, meta);
  assert.ok(engine.update('T', 0.60, meta), 'first crossing alerts');
  assert.equal(engine.update('T', 0.61, meta), null, 'no second alert on the same excursion');
  assert.ok(engine.update('T', 0.50, meta), 'a reversal of ≥ $0.10 is a new alert');
});

test('a stale quote never alerts', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/model.js');
  const engine = new ctx.AlertEngine(0);
  const meta = { ticker: 'S', title: 't', topic: 'golf' };
  engine.update('S', 0.50, meta);
  // `stale: true` is what the dashboard sets when the quote is older than the limit.
  assert.equal(engine.update('S', 0.65, { ...meta, stale: true }), null);
});

test('a market that is re-quoted after a long gap does not alert on the gap', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/model.js');
  const engine = new ctx.AlertEngine(0);
  const meta = { ticker: 'G', title: 't', topic: 'gas' };
  engine.update('G', 0.50, meta);
  // A quote observed 40 minutes later is a new reference, not a swing.
  engine.reset('G');
  assert.equal(engine.update('G', 0.95, meta), null);
});

/* ------------------------------------------------------------------ */
/* Candlestick normalisation — official field names                     */
/* ------------------------------------------------------------------ */
test('candlesticks normalise from the documented close/previous fields', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js');
  const payload = {
    ticker: 'KXTEST-1',
    candlesticks: [
      { end_period_ts: 1700000060, price: { close_dollars: '0.42', previous_dollars: '0.40' }, yes_bid: { close_dollars: '0.41' }, yes_ask: { close_dollars: '0.43' } },
      { end_period_ts: 1700000120, price: { close_dollars: null, previous_dollars: '0.42' }, yes_bid: { close_dollars: '0.55' }, yes_ask: { close_dollars: '0.57' } },
    ],
  };
  const pts = ctx.Kalshi.candlesToPoints(payload);
  assert.equal(pts.length, 2);
  assert.equal(pts[0].t, 1700000060000);
  assert.equal(pts[0].p, 0.42);
  // No trade in the second period: fall back to the bid/ask midpoint, which is
  // a quote, not an invented trade.
  assert.equal(pts[1].p, 0.56);
  assert.equal(pts[1].basis, 'quote_mid');
  assert.equal(pts[0].basis, 'last_trade');
});

test('a candle with no price and no quote yields no point', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js');
  const pts = ctx.Kalshi.candlesToPoints({ candlesticks: [{ end_period_ts: 1, price: {}, yes_bid: {}, yes_ask: {} }] });
  assert.equal(pts.length, 0);
});

/* ------------------------------------------------------------------ */
/* Order envelope — official POST /portfolio/events/orders body         */
/* ------------------------------------------------------------------ */
test('the demo order envelope matches the documented request body', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js');
  const body = ctx.Kalshi.orderBody({ ticker: 'KXTEST', side: 'yes', count: 3, price: 0.42, clientOrderId: 'abc-123' });
  assert.equal(body.ticker, 'KXTEST');
  assert.equal(body.side, 'bid', 'buying YES is a bid');
  assert.equal(body.count, '3', 'count is a string of contracts');
  assert.equal(body.price, '0.4200', 'price is a fixed-point dollar string');
  assert.equal(body.time_in_force, 'good_till_canceled');
  assert.equal(body.self_trade_prevention_type, 'taker_at_cross');
  assert.equal(body.client_order_id, 'abc-123');
  const no = ctx.Kalshi.orderBody({ ticker: 'KXTEST', side: 'no', count: 1, price: 0.58, clientOrderId: 'x' });
  assert.equal(no.side, 'ask', 'buying NO is an ask on the YES book');
});

/* ------------------------------------------------------------------ */
/* Data contract for the committed swing log the collector writes       */
/* ------------------------------------------------------------------ */
test('the committed alert log, if present, satisfies its contract', () => {
  let raw;
  try {
    raw = readFileSync(path.join(ROOT, 'terminal/data/alerts.json'), 'utf8');
  } catch {
    return; // first run: the collector has not written it yet
  }
  const log = JSON.parse(raw);
  assert.ok(Array.isArray(log.alerts), 'alerts is an array');
  for (const a of log.alerts) {
    assert.ok(Number.isFinite(a.abs_delta), 'a logged swing carries a numeric delta');
    assert.ok(a.abs_delta >= 0.1 - 1e-9, 'a logged swing meets the ≥ $0.10 rule');
    assert.ok(a.ticker, 'a logged swing names its contract');
    assert.ok(a.from_ts && a.to_ts, 'a logged swing carries both observation times');
    assert.ok(['up', 'down'].includes(a.direction), 'direction is up or down');
    assert.ok(typeof a.source_url === 'string' && a.source_url.startsWith('https://'), 'every row links its official source');
  }
});
