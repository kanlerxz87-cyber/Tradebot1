import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { openPosition, markToMarket } from '../tools/strategies.mjs';

test('openPosition and markToMarket honor series feeMultiplier = 0 and > 1', () => {
  const zeroFeePos = openPosition({
    ticker: 'KXETHY-27JAN01-T4000',
    topic: 'crypto',
    strategyId: 'longshot',
    side: 'yes',
    price: 0.02,
    contracts: 1,
    at: '2026-11-27T19:45:00Z',
    title: 'ETH price EOY?',
    eventTicker: 'KXETHY-27JAN01',
    reason: 'longshot: ask $0.0200',
    feeMultiplier: 0,
  });
  assert.equal(zeroFeePos.entryFee, 0);
  assert.equal(zeroFeePos.feeMultiplier, 0);

  const zeroMtm = markToMarket(zeroFeePos, { yesBid: 0.05, noBid: 0.95 });
  assert.equal(zeroMtm.exitFee, 0);
  assert.equal(zeroMtm.unrealizedPnl, 0.03);

  const defaultPos = openPosition({
    ticker: 'KXBTCY-27JAN0100-T20000.00',
    topic: 'crypto',
    strategyId: 'longshot',
    side: 'yes',
    price: 0.01,
    contracts: 1,
    at: '2026-11-27T19:45:00Z',
    title: 'BTC price on Jan 1, 2027?',
    eventTicker: 'KXBTCY-27JAN0100',
    reason: 'longshot: ask $0.0100',
    feeMultiplier: 1,
  });
  assert.equal(defaultPos.entryFee, 0.01);
  assert.equal(defaultPos.feeMultiplier, 1);
});

test('committed portfolio.json never carries a stale empty-portfolio note when positions exist', () => {
  const portfolio = JSON.parse(readFileSync(new URL('../data/live/portfolio.json', import.meta.url), 'utf8'));
  if ((portfolio.positions ?? []).length > 0) {
    assert.ok(!String(portfolio.note ?? '').includes('No simulated position has been opened yet'));
  }
});
