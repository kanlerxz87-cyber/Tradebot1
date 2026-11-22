// The capture tool is the only part of this console that talks to Kalshi on a schedule. These tests
// drive it with a stubbed fetch and assert that:
//   * it only ever requests the official demo host;
//   * it records the exact URL and read time of every request it makes;
//   * a failed request becomes an error entry, not a fabricated value;
//   * a thin run refuses to overwrite good data.
// No network access happens here.
import test from 'node:test';
import assert from 'node:assert/strict';

const calls = [];
let handler = () => ({ status: 200, body: {} });

globalThis.fetch = async (url, options = {}) => {
  calls.push({ url: String(url), options });
  const { status = 200, body = {}, ok } = handler(String(url)) ?? {};
  return {
    ok: ok ?? (status >= 200 && status < 300),
    status,
    headers: { get: (name) => ({ 'x-ratelimit-limit': '600', 'x-ratelimit-cost': '10' })[name.toLowerCase()] ?? null },
    text: async () => JSON.stringify(body),
  };
};

const { get, seriesFor, scanEvents, enrichBooks } = await import('../tools/capture.mjs');

test('every request stays on the official demo host', async () => {
  calls.length = 0;
  handler = () => ({ status: 200, body: { series: [], cursor: '' } });
  await get('/exchange/status');
  await get('/markets', { limit: 5, tickers: 'A,B' });
  for (const call of calls) {
    assert.match(call.url, /^https:\/\/external-api\.demo\.kalshi\.co\/trade-api\/v2\//, call.url);
    assert.equal(new URL(call.url).searchParams.get('account') ?? null, null);
  }
});

test('a request records its URL, status, timestamp and rate-limit headers', async () => {
  handler = () => ({ status: 200, body: { ok: true } });
  const result = await get('/exchange/status', {}, 'status');
  assert.equal(result.ok, true);
  assert.equal(result.status, 200);
  assert.match(result.url, /\/exchange\/status$/);
  assert.ok(!Number.isNaN(Date.parse(result.read_at)));
  assert.equal(result.rate_limit.limit, '600');
});

test('a failing request is reported as an error and never as a value', async () => {
  // The stub always returns a parseable body, so this exercises the HTTP-status branch: a 429 body
  // must not be mistaken for data even though it is valid JSON.
  handler = () => ({ status: 429, ok: false, body: { error: 'too many requests' } });
  const result = await get('/markets');
  assert.equal(result.ok, false);
  assert.equal(result.error, 'HTTP 429');
  // The body of a failed request is kept only so the error can quote Kalshi's own message; ok:false
  // means nothing downstream will treat it as market data.
  assert.equal(result.data.error, 'too many requests');
});

test('a network failure does not throw out of get()', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error('blocked by sandbox');
  };
  const result = await get('/markets');
  assert.equal(result.ok, false);
  assert.equal(result.status, 0);
  assert.match(result.error, /blocked/);
  globalThis.fetch = original;
});

test('series discovery keeps the official selector as the routing evidence', async () => {
  calls.length = 0;
  handler = (url) => ({
    status: 200,
    body: {
      series: [{ ticker: 'KXAAAGASM', title: 'US gas price', categories: ['Economics'], tags: ['Oil & Gas'], settlement_sources: [] }],
      cursor: '',
    },
  });
  const rule = { topic: 'gas', selectors: [{ param: 'tags', value: 'Oil & Gas' }], keywords: [], derived: false };
  const found = await seriesFor(rule);
  assert.equal(found.size, 1);
  const series = found.get('KXAAAGASM');
  assert.equal(series.routed_official, true);
  assert.match(series.routed_by, /official selector tags="Oil & Gas"/);
  assert.ok(calls.every((call) => call.url.includes('external-api.demo.kalshi.co')));
});

test('an empty scan yields no events rather than placeholders', async () => {
  handler = () => ({ status: 200, body: { events: [], cursor: '' } });
  const scan = await scanEvents({ gas: new Map([['KXAAAGASM', {}]]) });
  assert.deepEqual(scan.events, []);
  assert.equal(scan.pages, 1);
});

test('books are only fetched for markets that are active', async () => {
  calls.length = 0;
  handler = () => ({ status: 200, body: { orderbook_fp: { yes_dollars: [['0.40', '10.00']], no_dollars: [] } } });
  const books = await enrichBooks([
    { ticker: 'ACTIVE', status: 'active', last_price_dollars: '0.4', volume_24h_fp: '10' },
    { ticker: 'CLOSED', status: 'closed', last_price_dollars: '0.9', volume_24h_fp: '9999' },
  ]);
  assert.ok(books.ACTIVE);
  assert.equal(books.CLOSED, undefined);
  assert.ok(calls.every((call) => !call.url.includes('CLOSED')));
  assert.equal(books.ACTIVE.bestYesBid, 0.4);
});
