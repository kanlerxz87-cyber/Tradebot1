/* tools/terminal-collect.test.mjs — the swing-log collector's rules, offline.
 *
 * These tests pin the two things a wrong collector would do to the published site:
 * report a move that never happened (carry a price forward, compare across a gap,
 * or threshold on a rounded value), and lose the log's integrity on merge.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { priceOf, classify, detectSwing, mergeAlerts } from './terminal-collect.mjs';

test('the collector measures a price the way the dashboard does', () => {
  assert.deepEqual(priceOf({ last_price_dollars: '0.4200', yes_bid_dollars: '0.40', yes_ask_dollars: '0.44' }), { price: 0.42, basis: 'last_trade' });
  assert.deepEqual(priceOf({ yes_bid_dollars: '0.4000', yes_ask_dollars: '0.4400' }), { price: 0.42, basis: 'quote_mid' });
  assert.deepEqual(priceOf({ yes_bid_dollars: '0.4000', yes_ask_dollars: null }), { price: null, basis: 'unpriced' });
  assert.deepEqual(priceOf({ yes_bid_dollars: '0.0000', yes_ask_dollars: '1.0000' }), { price: null, basis: 'unpriced' });
  assert.deepEqual(priceOf({}), { price: null, basis: 'unpriced' });
});

test('classification uses series, then tag, then category, then words', () => {
  assert.equal(classify({ seriesTicker: 'KXAAAGASM', tags: [], category: 'Economics' }).topic, 'gas');
  assert.equal(classify({ seriesTicker: 'KXPGATOUR', tags: [], category: 'Sports' }).topic, 'golf');
  assert.equal(classify({ seriesTicker: 'X', tags: ['Golf'], category: 'Sports', title: 'Presidents Cup' }).topic, 'golf');
  assert.equal(classify({ seriesTicker: 'X', tags: [], category: 'Elections', title: 'Presidents Cup: X wins' }).topic, 'elections');
  assert.equal(classify({ seriesTicker: 'KXBTCD', tags: ['Bitcoin'], category: 'Crypto' }).topic, 'crypto');
  assert.equal(classify({ seriesTicker: 'X', tags: [], category: 'Economics', title: 'S&P 500 выше 7000' }).topic, null);
});

test('a swing needs two observations at least $0.10 apart', () => {
  const base = { ticker: 'T', title: 't', topic: 'gas', basis: 'last_trade', sourceUrl: 'u' };
  const now = 1795790400;
  assert.equal(detectSwing({ ...base, price: 0.60, now, prev: { price: 0.50, ts: now - 600 } }).abs_delta, 0.1);
  assert.equal(detectSwing({ ...base, price: 0.599, now, prev: { price: 0.50, ts: now - 600 } }), null);
  assert.equal(detectSwing({ ...base, price: 0.40, now, prev: { price: 0.50, ts: now - 600 } }).direction, 'down');
  assert.equal(detectSwing({ ...base, price: 0.60, now, prev: null }), null, 'first observation cannot be a swing');
  assert.equal(detectSwing({ ...base, price: null, now, prev: { price: 0.50, ts: now - 600 } }), null);
});

test('a gap longer than the collection interval rebases instead of alerting', () => {
  const now = 1795790400;
  const a = detectSwing({ ticker: 'T', title: 't', topic: 'gas', basis: 'last_trade', sourceUrl: 'u', price: 0.60, now, prev: { price: 0.20, ts: now - 46 * 60 } });
  assert.equal(a, null, 'a 46-minute gap cannot be attributed to a $0.40 move');
});

test('the alert merge dedupes, refuses under-threshold rows and keeps newest first', () => {
  const now = 1795790400;
  const good = { id: 'a', ticker: 'T', abs_delta: 0.12, to_ts: now };
  const good2 = { id: 'b', ticker: 'T', abs_delta: 0.11, to_ts: now + 60 };
  const small = { id: 'c', ticker: 'T', abs_delta: 0.05, to_ts: now + 120 };
  const dup = { id: 'a', ticker: 'T', abs_delta: 0.12, to_ts: now };
  const merged = mergeAlerts([good, dup], [small, good2], 10);
  assert.equal(merged.length, 2);
  assert.deepEqual(merged.map((m) => m.id), ['b', 'a']);
});
