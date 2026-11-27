// The simulated strategies.
//
// Each strategy is a rule that reads only observed market data, and each is
// listed on the Strategies page with its exact trigger so a reader can
// reproduce or refute a simulated trade by hand.
//
// These are simulations against the Kalshi demo environment. Kalshi's own docs
// warn that demo prices and behaviour may not reflect real markets
// (https://docs.kalshi.com/getting_started/demo_env). Nothing here is a
// forecast of profit or a trading recommendation.

import { takerFee } from './fees.mjs';
import { round2, round4 } from './alerts.mjs';

export const STRATEGY_SOURCE = 'https://docs.kalshi.com/getting_started/demo_env';
export const ORDERBOOK_SOURCE = 'https://docs.kalshi.com/getting_started/orderbook_responses';
export const FEE_SOURCE = 'https://kalshi.com/docs/kalshi-fee-schedule.pdf';

/**
 * Entry rules. Input is a snapshot row for one market; output is null (no
 * trade) or { side, reason }.
 *
 * side 'yes' means buy YES; side 'no' means buy NO. Buying NO at price
 * (1 - yesBid) is what the order book offers, because a YES bid at X is a NO
 * ask at 1-X (docs: getting_started/orderbook_responses).
 */
export const STRATEGIES = [
  {
    id: 'momentum',
    name: 'Momentum (buy the move)',
    thesis: 'A verified >= $0.10 move continues for at least the rest of the observed window more often than not.',
    rule: 'When the last observed mid-price is >= $0.10 above the previous observation, buy YES at the best YES ask, provided the ask is <= $0.90 and no position is open in that market.',
    side: 'yes',
    evaluate: (row) => {
      if (row.lastDelta == null || row.lastDelta < 0.1) return null;
      const ask = row.yesAsk;
      if (ask == null || ask > 0.9 || ask <= 0) return null;
      return { side: 'yes', price: ask, reason: `momentum: last move +$${round2(row.lastDelta)}` };
    },
  },
  {
    id: 'fade',
    name: 'Fade (sell the spike)',
    thesis: 'A large move away from the middle is more likely to retrace than to extend.',
    rule: 'When the last observed mid-price is >= $0.10 above the previous observation and the new mid is above $0.60, buy NO at the best NO ask, provided that ask is <= $0.90.',
    side: 'no',
    evaluate: (row) => {
      if (row.lastDelta == null || row.lastDelta < 0.1) return null;
      if (row.yesMid == null || row.yesMid <= 0.6) return null;
      const noAsk = row.noAsk;
      if (noAsk == null || noAsk > 0.9 || noAsk <= 0) return null;
      return { side: 'no', price: noAsk, reason: `fade: +$${round2(row.lastDelta)} to ${round2(row.yesMid * 100)}c` };
    },
  },
  {
    id: 'dipbuy',
    name: 'Dip buyer',
    thesis: 'A >= $0.10 fall in a market that is still above $0.30 is an overreaction.',
    rule: 'When the last observed mid is >= $0.10 below the previous observation and still above $0.30, buy YES at the best YES ask, provided the ask is <= $0.90.',
    side: 'yes',
    evaluate: (row) => {
      if (row.lastDelta == null || row.lastDelta > -0.1) return null;
      if (row.yesMid == null || row.yesMid <= 0.3) return null;
      const ask = row.yesAsk;
      if (ask == null || ask > 0.9 || ask <= 0) return null;
      return { side: 'yes', price: ask, reason: `dip: -$${round2(-row.lastDelta)} to ${round2(row.yesMid * 100)}c` };
    },
  },
  {
    id: 'longshot',
    name: 'Longshot collector',
    thesis: 'Very cheap contracts are systematically underpriced relative to their true probability.',
    rule: 'When the best YES ask is <= $0.05 and there are at least 100 contracts resting at that price, buy YES at the ask.',
    side: 'yes',
    evaluate: (row) => {
      const ask = row.yesAsk;
      if (ask == null || ask <= 0 || ask > 0.05) return null;
      if (!(row.yesAskDepthContracts >= 100)) return null;
      return { side: 'yes', price: ask, reason: `longshot: ask $${ask.toFixed(4)}` };
    },
  },
  {
    id: 'favorite',
    name: 'Favorite carry',
    thesis: 'Markets already priced above 85c are more often right than wrong, and the edge is the carry.',
    rule: 'When the best YES ask is between $0.85 and $0.95 inclusive and the spread is $0.02 or less, buy YES at the ask.',
    side: 'yes',
    evaluate: (row) => {
      const ask = row.yesAsk;
      if (ask == null || ask < 0.85 || ask > 0.95) return null;
      if (row.spread == null || row.spread > 0.02) return null;
      return { side: 'yes', price: ask, reason: `favorite: ask $${ask.toFixed(4)} spread $${row.spread}` };
    },
  },
];

export const STRATEGY_BY_ID = Object.fromEntries(STRATEGIES.map((s) => [s.id, s]));

/**
 * Open a simulated position. Fees are the published taker fee. The cost of a
 * YES position at price p for n contracts is n*p; a NO position at price q is
 * n*q. Payout at settlement is $1 per winning contract, $0 per losing one.
 */
export function openPosition({ ticker, topic, strategyId, side, price, contracts, at, title, eventTicker, reason = '', feeMultiplier = 1 }) {
  if (!(contracts > 0)) throw new Error('contracts must be positive');
  const p = round4(price);
  if (!(p > 0 && p < 1)) throw new Error(`price out of range: ${price}`);
  const mult = feeMultiplier != null && Number.isFinite(Number(feeMultiplier)) && Number(feeMultiplier) >= 0 ? Number(feeMultiplier) : 1;
  const fee = takerFee(contracts, p, mult);
  const pos = {
    ticker, topic, strategyId, side, contracts: round2(contracts),
    entryPrice: p,
    entryCost: round2(contracts * p),
    entryFee: round2(fee),
    openedAt: at,
    title: title ?? '',
    eventTicker: eventTicker ?? '',
    reason,
    status: 'open',
    source: ORDERBOOK_SOURCE,
    feeSource: FEE_SOURCE,
  };
  if (mult !== 1) pos.feeMultiplier = mult;
  return pos;
}

/**
 * Settle an open position against a resolved market. Only a finalised binary
 * result settles; anything else returns null and the position stays open,
 * because "determined" can still be disputed (docs: market_lifecycle).
 */
export function settlePosition(position, market, at) {
  const result = market?.result;
  const finalized = market?.status === 'finalized';
  if (!finalized || (result !== 'yes' && result !== 'no')) return null;
  const won = position.side === result;
  const payout = won ? position.contracts : 0;
  const pnl = payout - position.entryCost - position.entryFee;
  return {
    ...position,
    status: 'settled',
    settledAt: at,
    result,
    won,
    payout: round2(payout),
    realizedPnl: round2(pnl),
  };
}

/**
 * Mark an open position to market using the price at which it could be closed:
 * a YES position exits at the YES bid, a NO position exits at the NO bid.
 * Returns null if that side of the book is empty; no assumed price.
 */
export function markToMarket(position, row) {
  const exit = position.side === 'yes' ? row?.yesBid : row?.noBid;
  if (exit == null) return null;
  const rawMult = row?.feeMultiplier ?? position?.feeMultiplier;
  const mult = rawMult != null && Number.isFinite(Number(rawMult)) && Number(rawMult) >= 0 ? Number(rawMult) : 1;
  const exitFee = takerFee(position.contracts, exit, mult);
  const pnl = position.contracts * exit - position.entryCost - position.entryFee - exitFee;
  return {
    exitPrice: round4(exit),
    exitFee: round2(exitFee),
    unrealizedPnl: round2(pnl),
    source: ORDERBOOK_SOURCE,
  };
}

/** Portfolio totals from settled and open positions. Never invents a value. */
export function portfolioSummary({ positions, startingCash = 0 }) {
  const settled = positions.filter((p) => p.status === 'settled');
  const open = positions.filter((p) => p.status === 'open');
  const realized = settled.reduce((s, p) => s + (p.realizedPnl ?? 0), 0);
  const unrealized = open.reduce((s, p) => s + (p.unrealizedPnl ?? 0), 0);
  const fees = positions.reduce((s, p) => s + (p.entryFee ?? 0) + (p.exitFee ?? 0), 0);
  const staked = open.reduce((s, p) => s + p.entryCost + p.entryFee, 0);
  const wins = settled.filter((p) => p.won).length;
  return {
    startingCash: round2(startingCash),
    positions: positions.length,
    openPositions: open.length,
    settledPositions: settled.length,
    wins,
    losses: settled.length - wins,
    winRate: settled.length ? round4(wins / settled.length) : null,
    realizedPnl: round2(realized),
    unrealizedPnl: round2(unrealized),
    totalPnl: round2(realized + unrealized),
    feesPaid: round2(fees),
    stakedInOpenPositions: round2(staked),
    equity: round2(startingCash + realized + unrealized),
  };
}
