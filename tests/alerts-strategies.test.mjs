import test from 'node:test';
import assert from 'node:assert/strict';
import { detectSwing, yesMid, researchScore, resolutionOf, rankForFilteredFeed, SWING_THRESHOLD } from '../tools/alerts.mjs';
import { openPosition, settlePosition, markToMarket, portfolioSummary, STRATEGIES } from '../tools/strategies.mjs';
import { normaliseOrderbook } from '../tools/kalshi.mjs';

test('the swing threshold is the specified $0.10', () => {
  assert.equal(SWING_THRESHOLD, 0.1);
});

test('a move of exactly $0.10 qualifies, and $0.099 does not', () => {
  const base = { marketTicker: 'M', yesMid: 0.5 };
  assert.equal(detectSwing(base, { marketTicker: 'M', yesMid: 0.6 }).qualifies, true);
  assert.equal(detectSwing(base, { marketTicker: 'M', yesMid: 0.4 }).qualifies, true);
  assert.equal(detectSwing(base, { marketTicker: 'M', yesMid: 0.599 }).qualifies, false);
});

test('swing detection is symmetric and never invents a move from a missing price', () => {
  const up = detectSwing({ marketTicker: 'M', yesMid: 0.2 }, { marketTicker: 'M', yesMid: 0.35 });
  const down = detectSwing({ marketTicker: 'M', yesMid: 0.35 }, { marketTicker: 'M', yesMid: 0.2 });
  assert.equal(up.direction, 'up');
  assert.equal(down.direction, 'down');
  assert.equal(up.absDelta, down.absDelta);
  assert.equal(detectSwing({ marketTicker: 'M', yesMid: null }, { marketTicker: 'M', yesMid: 0.4 }), null);
  assert.equal(detectSwing({ marketTicker: 'A', yesMid: 0.1 }, { marketTicker: 'B', yesMid: 0.9 }), null);
});

test('mid price needs both sides and refuses a 0 bid / 1 ask pair', () => {
  assert.equal(yesMid(0.4, 0.42), 0.41);
  assert.equal(yesMid(0.4, null), null);
  assert.equal(yesMid(null, null), null);
  assert.equal(yesMid(0, 1), null);
});

test('AUD-01: one empty side is enough to disqualify a midpoint', () => {
  // The live shape of all eight markets in data/snapshot.json: a real 14c bid and a
  // reported ask of 1.0000 because the NO book is empty. (0.14 + 1.00) / 2 = 0.57 is a
  // phantom, not a quote. https://docs.kalshi.com/getting_started/orderbook_responses
  assert.equal(yesMid(0.14, 1.0), null);
  assert.equal(yesMid(0, 0.42), null);
});

test('order book ladder derives asks from the opposite side of the book', () => {
  // Live shape from external-api.demo.kalshi.co for KXELONMARS-99 on 2026-11-22.
  const book = normaliseOrderbook({ orderbook_fp: { yes_dollars: [['0.0100', '11285.32'], ['0.1400', '2718.76']], no_dollars: [] } });
  assert.equal(book.bestYesBid, 0.14);
  assert.equal(book.bestYesAsk, null); // no NO bids means no YES ask
  assert.equal(book.yesBidDepthContracts, 14004.08);
  assert.equal(book.yesBids[0][0], 0.14); // best bid first
});

test('a NO bid at 0.86 is a YES ask at 0.14', () => {
  const book = normaliseOrderbook({ orderbook_fp: { yes_dollars: [], no_dollars: [['0.8600', '500.00']] } });
  assert.equal(book.bestYesAsk, 0.14);
  assert.equal(book.yesAskDepthContracts, 500);
});

test('resolution mapping distinguishes finalized yes/no from awaiting', () => {
  assert.deepEqual(
    pick(resolutionOf({ status: 'finalized', result: 'yes' })),
    { state: 'resolved', result: 'yes', label: 'YES', final: true },
  );
  assert.deepEqual(
    pick(resolutionOf({ status: 'finalized', result: 'no' })),
    { state: 'resolved', result: 'no', label: 'NO', final: true },
  );
  assert.equal(resolutionOf({ status: 'determined', result: 'yes' }).final, false);
  assert.equal(resolutionOf({ status: 'closed', result: '' }).label, 'Awaiting result');
  assert.equal(resolutionOf({ status: 'active', result: '' }).label, 'Trading');
  assert.equal(resolutionOf({ status: 'finalized', result: 'scalar' }).state, 'scalar');
  assert.equal(resolutionOf({ status: 'finalized', result: '' }).label, 'Finalized, result not published');
});

test('research score is bounded, explainable and refuses thin markets', () => {
  const good = researchScore({ absDelta: 0.3, crossDepthContracts: 2000, spread: 0.01, volume24h: 400, ageSeconds: 10 });
  const thin = researchScore({ absDelta: 0.3, crossDepthContracts: 0, spread: 0.01, volume24h: 400, ageSeconds: 10 });
  assert.ok(good.score > thin.score);
  assert.equal(thin.eligible, false);
  const empty = researchScore({});
  assert.equal(empty.score, 0);
  assert.equal(empty.eligible, false);
  assert.ok(empty.missing.length === 5);
  for (const [k, v] of Object.entries(good.parts)) assert.ok(v >= 0, `${k} non-negative`);
  assert.ok(good.score <= 100);
});

test('filtered feed ranks by score then size then recency', () => {
  const ranked = rankForFilteredFeed([
    { score: 50, absDelta: 0.2, observedAt: 'b' },
    { score: 70, absDelta: 0.1, observedAt: 'a' },
    { score: 70, absDelta: 0.3, observedAt: 'c' },
  ]);
  assert.deepEqual(ranked.map((r) => r.absDelta), [0.3, 0.1, 0.2]);
});

test('a position is charged the published taker fee', () => {
  const p = openPosition({ ticker: 'T', topic: 'crypto', strategyId: 'momentum', side: 'yes', price: 0.5, contracts: 100, at: 'now' });
  assert.equal(p.entryCost, 50);
  assert.equal(p.entryFee, 1.75); // published 100-contract fee at 50c
});

test('a position only settles on a finalized binary result', () => {
  const p = openPosition({ ticker: 'T', topic: 'crypto', strategyId: 'm', side: 'yes', price: 0.5, contracts: 100, at: 'now' });
  assert.equal(settlePosition(p, { status: 'determined', result: 'yes' }, 'later'), null);
  assert.equal(settlePosition(p, { status: 'finalized', result: 'scalar' }, 'later'), null);
  const won = settlePosition(p, { status: 'finalized', result: 'yes' }, 'later');
  assert.equal(won.won, true);
  assert.equal(won.payout, 100);
  assert.equal(won.realizedPnl, 48.25); // 100 - 50 cost - 1.75 fee
  const lost = settlePosition({ ...p, side: 'no' }, { status: 'finalized', result: 'yes' }, 'later');
  assert.equal(lost.payout, 0);
  assert.equal(lost.realizedPnl, -51.75);
});

test('mark to market uses the executable side and refuses an empty book', () => {
  const p = openPosition({ ticker: 'T', topic: 'crypto', strategyId: 'm', side: 'yes', price: 0.5, contracts: 100, at: 'now' });
  assert.equal(markToMarket(p, { yesBid: null }), null);
  const marked = markToMarket(p, { yesBid: 0.6 });
  assert.equal(marked.exitPrice, 0.6);
  assert.ok(marked.unrealizedPnl > 0);
});

test('portfolio summary adds up and reports no win rate without settled trades', () => {
  const p = openPosition({ ticker: 'T', topic: 'crypto', strategyId: 'm', side: 'yes', price: 0.5, contracts: 100, at: 'now' });
  const s = portfolioSummary({ positions: [p], startingCash: 1000 });
  assert.equal(s.settledPositions, 0);
  assert.equal(s.winRate, null);
  assert.equal(s.equity, 1000);
  const closed = settlePosition(p, { status: 'finalized', result: 'yes' }, 'later');
  const s2 = portfolioSummary({ positions: [closed], startingCash: 1000 });
  assert.equal(s2.realizedPnl, 48.25);
  assert.equal(s2.equity, 1048.25);
  assert.equal(s2.winRate, 1);
});

test('every strategy has a documented rule, a side and an evaluate function', () => {
  for (const s of STRATEGIES) {
    assert.ok(s.id && s.name && s.rule && s.thesis, s.id);
    assert.equal(typeof s.evaluate, 'function');
  }
  assert.equal(new Set(STRATEGIES.map((s) => s.id)).size, STRATEGIES.length);
});

function pick({ state, result, label, final }) { return { state, result, label, final }; }
