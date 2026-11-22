// Unit tests for the live console's pure logic.
// Run: node --test docs/live/tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  num, quoteOf, bookOf, swing, triageScore, THRESHOLD, fee, feeCents, feeScheduleRow,
  routeSeries, TOPIC_RULES, resolutionOf, settlementOf, portfolioSummary, RANGES,
  candleIntervalFor, CANDLE_INTERVALS, withinRange, contractsForYesAtMost, contractsForYesAtLeast,
  walkYesBuy, fmtSigned, fmtCents,
} from '../assets/core.mjs';

/* ------------------------------------------------------------------ parsing */

test('num never turns a blank or junk value into zero', () => {
  assert.equal(num(''), null);
  assert.equal(num('   '), null);
  assert.equal(num(null), null);
  assert.equal(num(undefined), null);
  assert.equal(num('abc'), null);
  assert.equal(num('0.0000'), 0);
  assert.equal(num('13.00'), 13);
  assert.equal(num(0.56), 0.56);
});

test('a 0.0000 price and a 1.0000 empty-side ask are not quoted as a two-sided market', () => {
  // This is the exact demo shape: an empty book printed as bid 0 / ask 1 with last trade 0.98.
  const quote = quoteOf({
    yes_bid_dollars: '0.0000',
    yes_ask_dollars: '1.0000',
    no_bid_dollars: '0.0000',
    no_ask_dollars: '1.0000',
    last_price_dollars: '0.9800',
    yes_bid_size_fp: '0.00',
    yes_ask_size_fp: '0.00',
  });
  assert.equal(quote.twoSided, false);
  assert.equal(quote.mid, null, 'a midpoint of 0 and 1 would be an invented 50c');
  assert.equal(quote.mark, 0.98);
  assert.equal(quote.basis, 'last trade');
});

test('a genuinely two-sided quote uses the mid and reports the spread', () => {
  const quote = quoteOf({ yes_bid_dollars: '0.40', yes_ask_dollars: '0.42', last_price_dollars: '0.41' });
  assert.equal(quote.twoSided, true);
  assert.equal(quote.mid, 0.41);
  assert.equal(quote.spread, 0.02);
  assert.equal(quote.basis, 'mid');
});

test('the implied ask comes from the opposite best bid', () => {
  const quote = quoteOf({ yes_bid_dollars: '0.80', yes_ask_dollars: '1.0000', no_bid_dollars: '0.15' });
  assert.equal(quote.yesAsk, 0.85);
  assert.equal(quote.twoSided, true);
});

test('quoteOf exposes each fallback basis in order', () => {
  assert.equal(quoteOf({ yes_bid_dollars: '0.30' }).basis, 'best bid');
  assert.equal(quoteOf({ yes_ask_dollars: '0.70' }).basis, 'best ask');
  assert.equal(quoteOf({}).basis, 'none');
  assert.equal(quoteOf({}).mark, null);
});

/* ---------------------------------------------------------------- order book */

test('book levels are sorted best first and zero-size levels are dropped', () => {
  const book = bookOf({
    yes_dollars: [['0.0100', '200.00'], ['0.4200', '13.00'], ['0.3800', '0.00']],
    no_dollars: [['0.1600', '3.00'], ['0.5600', '17.00']],
  });
  assert.deepEqual(book.yes.map((level) => level.price), [0.42, 0.01]);
  assert.equal(book.bestYesBid, 0.42);
  assert.equal(book.yesAsk, 0.44, 'ask = 1 - best NO bid');
  assert.equal(book.spread, 0.02);
  assert.equal(book.empty, false);
});

test('an empty book is empty, not a zero price', () => {
  const book = bookOf({ yes_dollars: [], no_dollars: [] });
  assert.equal(book.empty, true);
  assert.equal(book.mid, null);
  assert.equal(book.spread, null);
  assert.equal(book.bestYesBid, null);
});

test('missing orderbook_fp does not throw', () => {
  const book = bookOf(undefined);
  assert.equal(book.empty, true);
});

test('contracts available at a price are summed, not assumed', () => {
  const book = bookOf({ no_dollars: [['0.1000', '50.00'], ['0.2000', '30.00']] });
  // Buying YES at 0.90 or better consumes NO bids of 0.10 and 0.20 only.
  assert.equal(contractsForYesAtMost(book, 0.9), 80);
  // Paying at most 85c for YES excludes the NO bid at 0.10 (which would cost 0.90).
  assert.equal(contractsForYesAtMost(book, 0.85), 30);
  assert.equal(contractsForYesAtLeast(bookOf({ yes_dollars: [['0.40', '10.00'], ['0.30', '10.00']] }), 0.35), 10);
});

test('walking the book reports an incomplete fill instead of inventing size', () => {
  const book = bookOf({ no_dollars: [['0.2000', '10.00'], ['0.3000', '10.00']] });
  const partial = walkYesBuy(book, 50);
  assert.equal(partial.complete, false);
  assert.equal(partial.filled, 20);
  const full = walkYesBuy(book, 10);
  assert.equal(full.complete, true);
  // The cheapest way to buy YES is to lift the highest NO bid: 1 - 0.30 = 0.70, not 1 - 0.20.
  assert.equal(full.averagePrice, 0.7);
});

/* -------------------------------------------------------------------- swings */

test('the swing threshold is inclusive at exactly $0.10 in both directions', () => {
  assert.equal(THRESHOLD, 0.1);
  const up = swing(0.4, 0.5);
  const down = swing(0.5, 0.4);
  assert.equal(up.delta, 0.1);
  assert.equal(up.direction, 'up');
  assert.equal(down.delta, -0.1);
  assert.equal(down.direction, 'down');
});

test('moves smaller than $0.10 are not swings, and a missing mark is never a move', () => {
  assert.equal(swing(0.4, 0.49), null);
  assert.equal(swing(0.4, null), null);
  assert.equal(swing(null, 0.4), null);
  assert.equal(swing(0.4, 0.51).delta, 0.11);
});

test('a swing records the previous price and the move as a share of it', () => {
  const move = swing(0.2, 0.35);
  assert.equal(move.previous, 0.2);
  assert.equal(move.current, 0.35);
  assert.equal(move.percentOfPrevious, 75);
});

/* --------------------------------------------------------------------- fees */

test('every published fee-table row reproduces in both columns', () => {
  // Transcribed from https://kalshi.com/docs/kalshi-fee-schedule.pdf (S12).
  const table = [
    [0.01, 0.01, 0.07], [0.05, 0.01, 0.34], [0.1, 0.01, 0.63], [0.15, 0.01, 0.9], [0.2, 0.02, 1.12],
    [0.25, 0.02, 1.32], [0.3, 0.02, 1.47], [0.35, 0.02, 1.6], [0.4, 0.02, 1.68], [0.45, 0.02, 1.74],
    [0.5, 0.02, 1.75], [0.55, 0.02, 1.74], [0.6, 0.02, 1.68], [0.65, 0.02, 1.6], [0.7, 0.02, 1.47],
    [0.75, 0.02, 1.32], [0.8, 0.02, 1.12], [0.85, 0.01, 0.9], [0.9, 0.01, 0.63], [0.95, 0.01, 0.34],
    [0.99, 0.01, 0.07],
  ];
  assert.equal(table.length, 21);
  for (const [price, one, hundred] of table) {
    const row = feeScheduleRow(price);
    assert.equal(row.oneContract, one, `one contract at ${price}`);
    assert.equal(row.hundredContracts, hundred, `100 contracts at ${price}`);
  }
});

test('fees are charged at six decimals before any balance rounding', () => {
  const sixDp = fee(0.5, 1);
  assert.equal(sixDp, 0.0175);
  assert.equal(feeCents(0.5, 1), 0.02, 'the published table rounds the same fee up to a cent');
  assert.equal(fee(0.5, 100), 1.75);
});

test('maker fees use the published 0.0175 rate and degenerate inputs cost nothing', () => {
  assert.equal(fee(0.5, 100, { maker: true }), 0.4375);
  assert.equal(fee(0, 10), 0);
  assert.equal(fee(1, 10), 0);
  assert.equal(fee(0.5, 0), 0);
  assert.equal(fee(null, 10), 0);
});

/* ------------------------------------------------------------------ routing */

test('every topic rule cites an official selector or declares itself derived', () => {
  for (const rule of TOPIC_RULES) {
    assert.ok(rule.selectors.length > 0, `${rule.topic} must have a selector`);
    for (const selector of rule.selectors) {
      assert.ok(selector.param === 'category' || selector.param === 'tags');
    }
    assert.equal(typeof rule.derived, 'boolean');
  }
});

test('routing uses the official selector before any keyword', () => {
  const gas = routeSeries({ ticker: 'KXAAAGASM', categories: ['Economics'], tags: ['Oil & Gas'] }, 'gas');
  assert.equal(gas.matched, true);
  assert.equal(gas.official, true);
  assert.match(gas.rule, /tag "Oil & Gas"/);
  const golf = routeSeries({ ticker: 'KXPGATOUR', categories: ['Sports'], tags: ['Golf'] }, 'golf');
  assert.match(golf.rule, /tag "Golf"/);
  const crypto = routeSeries({ ticker: 'KXBTCD', categories: ['Crypto'], tags: ['BTC'] }, 'crypto');
  assert.match(crypto.rule, /category "Crypto"/);
});

test('culture routes through Entertainment and says it is derived', () => {
  const culture = routeSeries({ ticker: 'KXOSCAR', categories: ['Entertainment'], tags: ['Oscars'] }, 'culture');
  assert.equal(culture.matched, true);
  assert.equal(culture.derived, true);
  assert.match(culture.rule, /Entertainment/);
});

test('a keyword match is flagged as not official, and no match is not a match', () => {
  const keyword = routeSeries({ ticker: 'KXGASPRICE', title: 'US gas price monthly', categories: ['Economics'], tags: [] }, 'gas');
  assert.equal(keyword.matched, true);
  assert.equal(keyword.official, false);
  assert.match(keyword.rule, /keyword/);
  const none = routeSeries({ ticker: 'KXNFLGAME', title: 'Pro Football Game', categories: ['Sports'], tags: ['Football'] }, 'golf');
  assert.equal(none.matched, false);
});

test('the demo BTC series is not routed to crypto, because Kalshi files it as Test', () => {
  const routed = routeSeries({ ticker: 'KXDEMOFUTHOURLY', title: 'Demo hourly event contract futures', categories: ['Test'], tags: ['Demo'] }, 'crypto');
  assert.equal(routed.matched, false);
});

/* --------------------------------------------------------------- resolution */

test('a result is reported only when the API supplies one', () => {
  assert.equal(resolutionOf({ status: 'active', result: '' }).result, null);
  assert.equal(resolutionOf({ status: 'closed', result: '' }).decided, false);
  assert.equal(resolutionOf({ status: 'determined', result: 'yes' }).label, 'Resolved YES');
  assert.equal(resolutionOf({ status: 'finalized', result: 'no' }).finalized, true);
  assert.equal(resolutionOf({ status: 'active', result: '' }).label, 'Open');
});

test('settlement pays $1 per YES contract only on a yes result and charges no settlement fee', () => {
  const position = { contracts: 10, entryPrice: 0.4, fee: 0.02 };
  assert.deepEqual(settlementOf(position, 'yes'), { payout: 10, realised: 5.98 });
  assert.deepEqual(settlementOf(position, 'no'), { payout: 0, realised: -4.02 });
  assert.equal(settlementOf(position, ''), null);
});

/* ------------------------------------------------------------------ ledger */

test('portfolio equity is cash plus marked positions and counts what it cannot price', () => {
  const ledger = {
    cash: 500,
    positions: [
      { ticker: 'A', contracts: 10, entryPrice: 0.5 },
      { ticker: 'B', contracts: 4, entryPrice: 0.25 },
    ],
    fills: [{ realised: 2.5, fee: 0.1 }],
  };
  const summary = portfolioSummary(ledger, { A: 0.6 });
  assert.equal(summary.openValue, 6 + 1);
  assert.equal(summary.equity, 507);
  assert.equal(summary.unpricedPositions, 0);
  assert.equal(summary.fees, 0.1);
  // An explicit null mark is reported as unpriced rather than quietly priced at entry.
  assert.equal(portfolioSummary(ledger, { A: null }).unpricedPositions, 1);
  // A market absent from the marks map falls back to its entry price, which is stated, not hidden.
  assert.equal(portfolioSummary(ledger, {}).openValue, 6);
});

/* ------------------------------------------------------------------- ranges */

test('chart ranges map to a candlestick interval the API accepts', () => {
  for (const range of RANGES) {
    const interval = candleIntervalFor(range.ms);
    assert.ok(CANDLE_INTERVALS.includes(interval), `${range.id} -> ${interval}`);
  }
  assert.deepEqual(RANGES.map((range) => range.id), ['30s', '5m', '1h', '6h', '24h']);
  assert.equal(candleIntervalFor(30_000), 1);
  assert.equal(candleIntervalFor(86_400_000), 60);
});

test('points outside the window are dropped and the rest are ordered', () => {
  const now = 1_000_000;
  const samples = [
    { t: now - 10_000, mark: 0.4 },
    { t: now - 1_000_000, mark: 0.3 },
    { t: now - 2_000, mark: 0.5 },
  ];
  const kept = withinRange(samples, now, 30_000);
  assert.deepEqual(kept.map((point) => point.mark), [0.4, 0.5]);
  assert.deepEqual(withinRange(null, now, 30_000), []);
});

/* ---------------------------------------------------------------- triage */

test('the triage score is bounded, monotone in move size, and explains itself', () => {
  const small = triageScore({ moveAbs: 0.1, sizeAtTouch: 100, spread: 0.02, volume24h: 500 });
  const large = triageScore({ moveAbs: 0.5, sizeAtTouch: 900, spread: 0.01, volume24h: 5000 });
  assert.ok(large.score > small.score);
  assert.ok(large.score <= 100 && small.score >= 0);
  assert.ok(Object.keys(small.parts).includes('depth'));
  assert.equal(triageScore({}).score, 0);
});

/* ---------------------------------------------------------------- display */

test('display formatters never print a missing value as a number', () => {
  assert.equal(fmtCents(null), '—');
  assert.equal(fmtCents(0.1), '10¢');
  assert.equal(fmtSigned(0.1), '+10¢');
  assert.equal(fmtSigned(-0.1), '−10¢');
  assert.equal(fmtSigned(0), '±0¢');
});
