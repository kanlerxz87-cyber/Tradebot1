/* terminal/tests/desk.test.mjs — the reference rules in desk.js, exercised against a
 * recorded payload shape (terminal/tests/fixtures/events_nested.json), not the network.
 *
 * The fixture is generated from this repository's own captured Kalshi demo payloads
 * (docs/desk/data/latest.json + series.json, both fetched by earlier sessions from
 * https://external-api.demo.kalshi.co/trade-api/v2). It keeps the official field names
 * (`yes_bid_dollars`, `volume_24h_fp`, `previous_price_dollars`, `tags`, …) so a field
 * rename in desk.js fails here instead of silently blanking the live page.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const ROOT = path.resolve(new URL('../..', import.meta.url).pathname);

function load(...files) {
  const sandbox = {
    console, Date, Math, Number, String, Array, Object, JSON, Map, Set, Infinity, NaN,
    URLSearchParams, TextEncoder,
    fetch: () => Promise.reject(new Error('network disabled in tests')),
    document: { addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, createElement: () => ({ style: {}, appendChild() {} }), body: {} },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    setTimeout, clearTimeout,
  };
  sandbox.window = sandbox;
  const ctx = vm.createContext(sandbox);
  for (const f of files) vm.runInContext(readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  const names = ['SITE', 'store', 'TOPICS', 'TOPIC_BY_ID', 'classifyMarket', 'Kalshi', 'Desk', 'Model', 'AlertEngine', 'PaperFees'];
  return Object.assign(ctx, vm.runInContext(
    '({' + names.map((n) => `${n}: (typeof ${n} === 'undefined' ? undefined : ${n})`).join(',') + '})', ctx));
}

const fixture = () => JSON.parse(readFileSync(path.join(ROOT, 'terminal/tests/fixtures/events_nested.json'), 'utf8'));

function rows(ctx) {
  const out = [];
  const now = 1795790400000; // fixed clock so `stale` is deterministic
  for (const ev of fixture().events) {
    for (const m of ev.markets) {
      const r = ctx.Desk.buildRow(ev, m, now);
      if (r) out.push(r);
    }
  }
  return out;
}

test('the fixture produces only the five focus topics, and every row names its evidence', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const r = rows(ctx);
  assert.ok(r.length > 0, 'the fixture must produce rows');
  for (const row of r) {
    assert.ok(ctx.Desk.FOCUS.includes(row.topic), `${row.ticker} in focus set`);
    assert.ok(row.topicEvidence, `${row.ticker} carries classification evidence`);
    assert.ok(['series', 'tag', 'category', 'keyword', 'supplied'].includes(row.topicConfidence));
  }
});

test('no row is built without a price, and the price basis is stated', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  for (const row of rows(ctx)) {
    assert.ok(Number.isFinite(row.price), `${row.ticker} has a numeric price`);
    assert.ok(['last_trade', 'quote_mid'].includes(row.priceBasis));
  }
});

test('a bid-only market is not priced at the bid and not turned into a midpoint', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  // Real shape: KXAAAGASW-26NOV30-3.4800 has a 0.98 bid and no ask.
  const m = { ticker: 'X', yes_bid_dollars: '0.9800', yes_ask_dollars: null, tags: ['Oil and energy'], category: 'Economics', series_ticker: 'KXAAAGASW' };
  const row = ctx.Desk.buildRow({ event_ticker: 'E', title: 'gas' }, m, Date.now());
  // No last price and no two-sided quote ⇒ no price ⇒ the row is dropped.
  assert.equal(row, null);
});

test('a 0-bid / 1-ask book is empty, not a 50¢ market', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const m = { ticker: 'X', yes_bid_dollars: '0.0000', yes_ask_dollars: '1.0000', tags: ['Golf'], category: 'Sports', series_ticker: 'KXPGATOUR' };
  assert.equal(ctx.Desk.buildRow({ event_ticker: 'E', title: 'golf' }, m, Date.now()), null);
});

test('the one-day change uses the exchange previous price and is never guessed', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const m = { ticker: 'X', last_price_dollars: '0.6500', previous_price_dollars: '0.4200', tags: ['Golf'], category: 'Sports', series_ticker: 'KXPGATOUR' };
  const row = ctx.Desk.buildRow({ event_ticker: 'E', title: 'golf' }, m, Date.now());
  assert.equal(row.dayChange, 0.23);
  const no = ctx.Desk.buildRow({ event_ticker: 'E', title: 'golf' }, { ...m, previous_price_dollars: null }, Date.now());
  assert.equal(no.dayChange, null, 'missing previous price ⇒ null, not zero');
});

test('day movers are the rows at or over the threshold, sorted by size', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const mk = (ticker, last, prev) => ({ ticker, last_price_dollars: last, previous_price_dollars: prev, tags: ['Golf'], category: 'Sports', series_ticker: 'KXPGATOUR' });
  const rs = [
    ctx.Desk.buildRow({ event_ticker: 'A', title: 'a' }, mk('A1', '0.50', '0.40'), Date.now()),
    ctx.Desk.buildRow({ event_ticker: 'A', title: 'a' }, mk('A2', '0.50', '0.49'), Date.now()),
    ctx.Desk.buildRow({ event_ticker: 'A', title: 'a' }, mk('A3', '0.10', '0.31'), Date.now()),
  ].filter(Boolean);
  const movers = ctx.Desk.dayMovers(rs, { threshold: 0.10 });
  assert.equal(movers.length, 2, '$0.01 change is excluded');
  assert.equal(movers[0].ticker, 'A3', 'the larger absolute move sorts first');
});

test('event dollar volume is null unless every child market reports one', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const r = rows(ctx);
  const evs = ctx.Desk.groupEvents(r);
  assert.ok(evs.length > 0);
  for (const ev of evs) {
    if (ev.dollarVolume !== null) assert.ok(Number.isFinite(ev.dollarVolume));
    if (!ev.dollarVolumeComplete) assert.equal(ev.dollarVolume, null, 'incomplete totals are blank, not partial');
  }
});

test('the liquidity ladder reports contracts and dollars per level, asks implied from NO bids', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const book = ctx.Kalshi.normalizeBook({
    orderbook_fp: {
      yes_dollars: [['0.1000', '100.00'], ['0.1400', '50.00']],
      no_dollars: [['0.8000', '200.00']],
    },
  });
  const s = ctx.Desk.bookSummary(book);
  assert.equal(s.bestBid, 0.14);
  assert.equal(s.bidContracts, 150);
  assert.equal(s.bidDollars, 17, '0.10×100 + 0.14×50');
  assert.equal(s.bestAsk, 0.20, 'a NO bid at 0.80 is a YES offer at 0.20');
  assert.equal(s.askDollars, 40);
});

test('an empty book summarises to nulls, not zeros', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const s = ctx.Desk.bookSummary(ctx.Kalshi.normalizeBook({ orderbook_fp: { yes_dollars: [], no_dollars: [] } }));
  assert.equal(s.bidContracts, null);
  assert.equal(s.askContracts, null);
  assert.equal(s.bestBid, null);
});

test('chart merge keeps live poll points on top of candles at equal timestamps', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  const merged = ctx.Desk.mergeSeries(
    [{ t: 1000, p: 0.40 }, { t: 2000, p: 0.41 }],
    [{ t: 2000, p: 0.45 }, { t: 3000, p: 0.46 }],
  );
  assert.equal(merged.length, 3);
  assert.equal(merged.find((p) => p.t === 2000).p, 0.45);
  assert.equal(merged.find((p) => p.t === 2000).source, 'poll');
});

test('rows from the fixture carry an official source URL per row', () => {
  const ctx = load('terminal/assets/js/common.js', 'terminal/assets/js/topics.js', 'terminal/assets/js/kalshi.js', 'terminal/assets/js/desk.js');
  for (const row of rows(ctx)) {
    assert.match(row.sourceUrl, /^https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\/markets\//);
  }
});
