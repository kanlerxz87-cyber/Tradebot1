import test from 'node:test';
import assert from 'node:assert/strict';
import { createClient, assertOfficialHost, normaliseOrderbook, KalshiError } from '../tools/kalshi.mjs';
import { topicForSeries, TOPICS } from '../tools/topics.mjs';

/** A fake fetch that records calls and replies from a routing table. */
function fakeFetch(routes) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    const u = new URL(url);
    const key = u.pathname + (u.search || '');
    const body = routes[key] ?? routes[u.pathname] ?? routes['*'];
    if (body === undefined) {
      return { ok: false, status: 404, text: async () => JSON.stringify({ error: { code: 'not_found' } }) };
    }
    if (typeof body === 'function') return body(u);
    return { ok: true, status: 200, text: async () => JSON.stringify(body) };
  };
  impl.calls = calls;
  return impl;
}

const ROOT = 'https://external-api.demo.kalshi.co/trade-api/v2';

test('the client refuses any host that is not an official demo root', () => {
  assert.throws(() => createClient({ root: 'https://evil.example.com/trade-api/v2', fetchImpl: fakeFetch({}) }), KalshiError);
  assert.throws(() => createClient({ root: 'https://external-api.kalshi.com/trade-api/v2', fetchImpl: fakeFetch({}) }), KalshiError);
  assert.equal(assertOfficialHost(ROOT), ROOT);
  assert.equal(assertOfficialHost('https://demo-api.kalshi.co/trade-api/v2/markets'), 'https://demo-api.kalshi.co/trade-api/v2/markets');
});

test('a client for production must be told so explicitly', () => {
  assert.throws(() => createClient({ root: 'https://external-api.kalshi.com/trade-api/v2', environment: 'demo', fetchImpl: fakeFetch({}) }), KalshiError);
  assert.doesNotThrow(() => createClient({ root: 'https://external-api.kalshi.com/trade-api/v2', environment: 'production', fetchImpl: fakeFetch({}) }));
});

test('requests carry query parameters and only public headers', async () => {
  const fetchImpl = fakeFetch({ '/trade-api/v2/exchange/status': { exchange_active: true, trading_active: true } });
  const client = createClient({ root: ROOT, fetchImpl });
  const res = await client.exchangeStatus();
  assert.equal(res.exchange_active, true);
  assert.equal(fetchImpl.calls.length, 1);
  assert.equal(fetchImpl.calls[0].init.headers.Authorization, undefined);
  assert.equal(fetchImpl.calls[0].init.headers['KALSHI-ACCESS-KEY'], undefined);
});

test('pagination follows cursors and stops on an empty one', async () => {
  let page = 0;
  const fetchImpl = fakeFetch({
    '/trade-api/v2/series': () => {
      page += 1;
      const body = page === 1
        ? { series: [{ ticker: 'A' }], cursor: 'next' }
        : { series: [{ ticker: 'B' }], cursor: '' };
      return { ok: true, status: 200, text: async () => JSON.stringify(body) };
    },
  });
  const client = createClient({ root: ROOT, fetchImpl });
  const res = await client.listSeries({ category: 'Crypto' });
  assert.deepEqual(res.series.map((s) => s.ticker), ['A', 'B']);
  assert.equal(res.complete, true);
  assert.equal(fetchImpl.calls.length, 2);
});

test('a bad cursor cannot loop forever', async () => {
  const fetchImpl = fakeFetch({
    '/trade-api/v2/markets': { markets: [{ ticker: 'A' }], cursor: 'always-more' },
  });
  const client = createClient({ root: ROOT, fetchImpl });
  const res = await client.listMarkets({ status: 'open' });
  assert.equal(res.complete, false);
  assert.ok(res.pages <= 12);
});

test('an HTTP error surfaces status and the exchange error code', async () => {
  const fetchImpl = fakeFetch({
    '/trade-api/v2/markets/NOPE': { error: { code: 'not_found' } },
  });
  const failing = async (url, init) => ({ ok: false, status: 404, text: async () => JSON.stringify({ error: { code: 'not_found' } }) });
  const client = createClient({ root: ROOT, fetchImpl: failing });
  await assert.rejects(() => client.getMarket('NOPE'), (err) => {
    assert.ok(err instanceof KalshiError);
    assert.equal(err.status, 404);
    assert.equal(err.code, 'not_found');
    return true;
  });
});

test('order book normalisation keeps quantity per price level and derives the other side', () => {
  const book = normaliseOrderbook({
    orderbook_fp: {
      yes_dollars: [['0.0100', '11285.32'], ['0.1400', '2718.76'], ['0.5000', '10.00']],
      no_dollars: [['0.8600', '500.00']],
    },
  });
  assert.equal(book.bestYesBid, 0.5);
  assert.equal(book.bestYesAsk, 0.14);
  assert.equal(book.yesBids[0][0], 0.5);
  assert.equal(book.yesAsks[0][0], 0.14);
  assert.equal(book.yesAskDepthContracts, 500);
  assert.equal(book.yesBidDepthContracts, 14014.08);
  // Best ask (0.14) is below the best bid (0.50) only because they are the two
  // sides of a crossed book in this synthetic fixture; the spread is reported
  // as the raw difference so a crossed book is visible rather than hidden.
  assert.equal(book.spread, -0.36);
});

test('an empty order book produces nulls, not zeros', () => {
  const book = normaliseOrderbook({ orderbook_fp: { yes_dollars: [], no_dollars: [] } });
  assert.equal(book.bestYesBid, null);
  assert.equal(book.bestYesAsk, null);
  assert.equal(book.spread, null);
  assert.equal(book.yesBidDepthContracts, 0);
});

test('topics map from the series fields the API actually returns', () => {
  assert.equal(topicForSeries({ category: 'Crypto' }), 'crypto');
  assert.equal(topicForSeries({ category: 'Elections' }), 'elections');
  assert.equal(topicForSeries({ category: 'Culture' }), 'culture');
  assert.equal(topicForSeries({ category: 'Sports', tags: ['Golf'] }), 'golf');
  assert.equal(topicForSeries({ category: 'Economics', tags: ['Gas'] }), 'gas');
  assert.equal(topicForSeries({ category: 'Sports', tags: ['NFL'] }), null);
  // A word in a title must not be enough. An Elections series whose title
  // mentions gas routes to Elections, never to gas.
  assert.equal(topicForSeries({ category: 'Elections', tags: [], title: 'Georgia gas prices' }), 'elections');
  assert.equal(topicForSeries({ category: 'World', tags: [], title: 'gas prices in Georgia the country' }), null);
});

test('there are exactly five focus topics with stable ids', () => {
  assert.deepEqual(TOPICS.map((t) => t.id).sort(), ['crypto', 'culture', 'elections', 'gas', 'golf']);
  for (const t of TOPICS) {
    assert.ok(t.discovery.length > 0, t.id);
    for (const d of t.discovery) assert.ok(d.url.startsWith('https://external-api.demo.kalshi.co/trade-api/v2/series?'), t.id);
  }
});

// Rate-limit behaviour. The demo API answered 429 to 25 series reads in one
// collector cycle on 2026-11-22, so the client must pace itself and retry with
// backoff instead of dropping the series from the topic.

test('a 429 is retried with backoff and the successful body is returned', async () => {
  let calls = 0;
  const slept = [];
  const client = createClient({
    fetchImpl: async () => {
      calls += 1;
      if (calls < 3) {
        return { ok: false, status: 429, headers: new Map([['retry-after', '1']]), text: async () => '{"error":{"code":"too_many_requests"}}' };
      }
      return { ok: true, status: 200, headers: new Map(), text: async () => '{"exchange_active":true}' };
    },
    minIntervalMs: 0,
    sleepImpl: async (ms) => { slept.push(ms); },
  });
  const body = await client.request('/exchange/status');
  assert.equal(calls, 3);
  assert.equal(body.exchange_active, true);
  assert.deepEqual(slept, [1000, 1000], 'Retry-After seconds are honoured');
  assert.equal(client.stats().retries, 2);
});

test('a 429 that never clears gives up after the retry budget', async () => {
  let calls = 0;
  const client = createClient({
    fetchImpl: async () => {
      calls += 1;
      return { ok: false, status: 429, headers: new Map(), text: async () => '{"error":{"code":"too_many_requests"}}' };
    },
    minIntervalMs: 0,
    maxRetries: 2,
    baseBackoffMs: 10,
    sleepImpl: async () => {},
  });
  await assert.rejects(() => client.request('/markets'), /HTTP 429/);
  assert.equal(calls, 3, 'one attempt plus two retries');
});

test('a non-retryable status is not retried', async () => {
  let calls = 0;
  const client = createClient({
    fetchImpl: async () => {
      calls += 1;
      return { ok: false, status: 404, headers: new Map(), text: async () => '{"error":{"code":"not_found"}}' };
    },
    minIntervalMs: 0,
    sleepImpl: async () => {},
  });
  await assert.rejects(() => client.request('/markets/nope'), /HTTP 404/);
  assert.equal(calls, 1);
});

test('requests are spaced by minIntervalMs', async () => {
  const slept = [];
  let clock = 0;
  const client = createClient({
    fetchImpl: async () => ({ ok: true, status: 200, headers: new Map(), text: async () => '{}' }),
    minIntervalMs: 300,
    nowImpl: () => clock,
    sleepImpl: async (ms) => { slept.push(ms); clock += ms; },
  });
  await client.request('/a');
  await client.request('/b');
  assert.ok(slept.length >= 1 && slept[0] === 300, `expected a 300ms pause, got ${JSON.stringify(slept)}`);
});
