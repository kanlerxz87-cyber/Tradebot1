import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  PUBLISHED_SERIES_MULTIPLIERS,
  seriesMultiplier,
  seriesFromTicker,
  takerFee,
  makerFee,
  MULTIPLIER_SOURCE,
} from '../tools/fees.mjs';
import { openPosition, markToMarket } from '../tools/strategies.mjs';

// Kalshi's published per-series multipliers, from the "Non-Standard Fees" table of
// https://kalshi.com/docs/kalshi-fee-schedule.pdf (effective 2026-07-07).
// A series listed 0/0 pays no fee; a series listed 1/1 pays the general fee.

test('the published zero-multiplier series pay no taker or maker fee', () => {
  const zero = Object.entries(PUBLISHED_SERIES_MULTIPLIERS).filter(([, row]) => row.maker === 0 && row.taker === 0);
  assert.ok(zero.length >= 9, `expected at least nine 0/0 rows, found ${zero.length}`);
  for (const [series, row] of zero) {
    assert.equal(row.maker, 0, `${series} maker`);
    assert.equal(row.taker, 0, `${series} taker`);
    assert.equal(takerFee(100, 0.5, seriesMultiplier(series, 'taker')), 0, `${series} taker fee`);
    assert.equal(makerFee(100, 0.5, seriesMultiplier(series, 'maker')), 0, `${series} maker fee`);
  }
});

test('the schedule rows read as 1/1 keep the general fee', () => {
  // Source rows: "KXCPI | CPI | 1 | 1", "KXFED | Fed funds rate | 1 | 1".
  // An earlier docstring in kalshi_trader/fees.py named these as fee-free; they are not.
  for (const series of ['KXCPI', 'KXFED', 'KXAAAGASM', 'KXCPIYOY']) {
    assert.equal(seriesMultiplier(series, 'taker'), 1, `${series} taker`);
    assert.equal(seriesMultiplier(series, 'maker'), 1, `${series} maker`);
    assert.equal(takerFee(100, 0.5, seriesMultiplier(series, 'taker')), 1.75, `${series} fee`);
  }
});

test('an unknown series falls back to the general multiplier of one', () => {
  assert.equal(seriesMultiplier('KXNOTINTHEPUBLISHEDTABLE'), 1);
  assert.equal(seriesMultiplier(undefined), 1);
  assert.equal(seriesMultiplier(null, 'maker'), 1);
});

test('series tickers are read from the front of the market ticker', () => {
  assert.equal(seriesFromTicker('KXBTCY-27JAN0100-T20000.00'), 'KXBTCY');
  assert.equal(seriesFromTicker('KXAAAGASM-26DEC-T3.50'), 'KXAAAGASM');
  assert.equal(seriesFromTicker('KXBTCY'), 'KXBTCY');
  assert.equal(seriesFromTicker(''), '');
});

test('a simulated KXBTCY fill is free, and the position records why', () => {
  const position = openPosition({
    ticker: 'KXBTCY-27JAN0100-T20000.00', topic: 'crypto', strategyId: 'longshot',
    side: 'yes', price: 0.01, contracts: 1, at: '2026-11-27T00:00:00Z',
  });
  assert.equal(position.entryFee, 0);
  assert.equal(position.seriesTicker, 'KXBTCY');
  assert.equal(position.feeMultiplier, 0);
  assert.equal(position.feeMultiplierSource, MULTIPLIER_SOURCE);
  assert.equal(position.entryCost, 0.01);
});

test('a simulated KXAAAGASM fill keeps the general fee and its multiplier', () => {
  const position = openPosition({
    ticker: 'KXAAAGASM-26DEC-T3.50', topic: 'gas', strategyId: 'momentum',
    side: 'yes', price: 0.5, contracts: 100, at: '2026-11-27T00:00:00Z',
    seriesTicker: 'KXAAAGASM',
  });
  assert.equal(position.entryFee, 1.75);
  assert.equal(position.feeMultiplier, 1);
});

test('mark-to-market uses the same published multiplier for the exit fill', () => {
  const free = openPosition({
    ticker: 'KXBTCY-27JAN0100-T20000.00', topic: 'crypto', strategyId: 'longshot',
    side: 'yes', price: 0.01, contracts: 1, at: '2026-11-27T00:00:00Z',
  });
  const marked = markToMarket(free, { yesBid: 0.01, noBid: 0.98 });
  assert.equal(marked.exitFee, 0);
  assert.equal(marked.unrealizedPnl, 0);
});

test('every committed simulated fill was charged its published multiplier', async () => {
  const portfolio = JSON.parse(await readFile(new URL('../data/live/portfolio.json', import.meta.url)));
  for (const position of portfolio.positions) {
    const series = position.seriesTicker || seriesFromTicker(position.ticker);
    const multiplier = seriesMultiplier(series, 'taker');
    assert.equal(
      position.entryFee,
      Math.round((takerFee(position.contracts, position.entryPrice, multiplier) + Number.EPSILON) * 100) / 100,
      `${position.ticker} entry fee`,
    );
    assert.equal(position.feeMultiplier ?? multiplier, multiplier, `${position.ticker} recorded multiplier`);
  }
  assert.equal(portfolio.summary.feesPaid, 0, 'the committed book holds only fee-free KXBTCY fills');
});

test('an exchange-published fee_multiplier takes precedence over the schedule table', () => {
  // GET /series documents `fee_multiplier` as "a floating point multiplier applied to the
  // fee calculations": https://docs.kalshi.com/api-reference/market/get-series
  const doubled = openPosition({
    ticker: 'KXSOMETHING-1', topic: 'crypto', strategyId: 'momentum',
    side: 'yes', price: 0.5, contracts: 100, at: '2026-11-27T00:00:00Z',
    seriesTicker: 'KXSOMETHING', feeMultiplier: 2,
  });
  assert.equal(doubled.feeMultiplier, 2);
  assert.equal(doubled.entryFee, 3.5);
  assert.equal(doubled.feeMultiplierSource, 'https://docs.kalshi.com/api-reference/market/get-series');

  // A published zero is honoured, not treated as a missing value.
  const free = openPosition({
    ticker: 'KXAAAGASM-1', topic: 'gas', strategyId: 'momentum',
    side: 'yes', price: 0.5, contracts: 100, at: '2026-11-27T00:00:00Z',
    seriesTicker: 'KXAAAGASM', feeMultiplier: 0,
  });
  assert.equal(free.entryFee, 0);
  assert.equal(free.feeMultiplier, 0);

  // A missing value falls back to the published schedule row.
  const fromTable = openPosition({
    ticker: 'KXAAAGASM-1', topic: 'gas', strategyId: 'momentum',
    side: 'yes', price: 0.5, contracts: 100, at: '2026-11-27T00:00:00Z',
    seriesTicker: 'KXAAAGASM', feeMultiplier: null,
  });
  assert.equal(fromTable.entryFee, 1.75);
  assert.equal(fromTable.feeMultiplierSource, MULTIPLIER_SOURCE);
});
