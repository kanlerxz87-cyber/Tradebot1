/* store.js — local paper portfolio (unrelated to the demo account) + shared helpers.
   Positions are YES contracts, marked against the latest price we have seen.
   Fees use the Kalshi taker formula  roundup(0.07 × C × P × (1−P))  per trade. */
'use strict';

/* Taker fee, exactly as the published schedule states it:
     fees = roundup(M × 0.07 × C × P × (1 − P)),  M = 1 by default
   https://kalshi.com/docs/kalshi-fee-schedule.pdf  (effective 2026-07-07)
   The naive `Math.ceil(raw * 100) / 100` overcharges by a cent whenever the exact
   fee already lands on a cent boundary, because the binary float lands just above
   it: 0.07 × 100 × 0.10 × 0.90 = 0.6300000000000001 → ceil → $0.64, while the
   published table says $0.63. Rounding to 6dp (the schedule's own granularity,
   see docs.kalshi.com/getting_started/fee_rounding) before the ceiling removes
   that error. terminal/tests/core.test.mjs reproduces all 42 published values. */
const PaperFees = {
  /* Round up (never down) to a quantum, in the quantum's own integer units, so the
     multiply back to dollars cannot reintroduce binary-float noise:
     0.07×100×0.20×(1−0.20) evaluates to 1.1200000000000003 in IEEE-754; a plain
     Math.ceil(x*100)/100 turns that into $1.13 while the published table says $1.12. */
  roundUp(value, quantum) {
    if (!Number.isFinite(value)) return 0;
    const units = Number((value / quantum).toPrecision(12));
    return Math.ceil(units) * quantum;
  },
  taker(count, price, multiplier = 1) {
    if (!(count > 0) || !(price >= 0)) return 0;
    return Number(PaperFees.roundUp(multiplier * 0.07 * count * price * (1 - price), 0.01).toFixed(2));
  },
  /* Six-decimal granularity for ledgers that must not lose fractions of a cent
     (docs.kalshi.com/getting_started/fee_rounding). */
  taker6(count, price, multiplier = 1) {
    if (!(count > 0) || !(price >= 0)) return 0;
    return Number(PaperFees.roundUp(multiplier * 0.07 * count * price * (1 - price), 1e-6).toFixed(6));
  },
};

const PaperPortfolio = (() => {
  const KEY = 'paper';
  const START_CASH = 10000;

  function blank() {
    return { cash: START_CASH, positions: [], trades: [], realizedPnl: 0, createdAt: Date.now() };
  }

  function load() {
    const p = store.get(KEY, null);
    if (!p || typeof p.cash !== 'number' || !Array.isArray(p.positions) || !Array.isArray(p.trades)) return blank();
    return p;
  }

  const save = (p) => store.set(KEY, p);

  function buy({ ticker, topic, title, qty, price }) {
    const p = load();
    const fee = PaperFees.taker(qty, price);
    const cost = qty * price + fee;
    if (cost > p.cash) return { ok: false, error: `Insufficient paper cash (need ${fmtUsd(cost)}, have ${fmtUsd(p.cash)}).` };
    p.cash -= cost;
    const pos = p.positions.find(x => x.ticker === ticker);
    if (pos) {
      const newQty = pos.qty + qty;
      pos.avgPrice = (pos.qty * pos.avgPrice + qty * price) / newQty;
      pos.qty = newQty;
      pos.lastMark = price;
    } else {
      const ev = String(ticker).split('-').slice(0, 2).join('-');
      p.positions.push({ id: 'pos_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7), ticker, eventTicker: ev, topic, title, qty, avgPrice: price, lastMark: price, openedAt: Date.now() });
    }
    const trade = { id: 'trd_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7), side: 'buy', ticker, topic, title, qty, price, fee, pnl: null, at: Date.now() };
    p.trades.push(trade);
    save(p);
    return { ok: true, fee, cost };
  }

  function sell({ positionId, qty, price }) {
    const p = load();
    const pos = p.positions.find(x => x.id === positionId);
    if (!pos) return { ok: false, error: 'Position not found.' };
    qty = Math.min(qty, pos.qty);
    const fee = PaperFees.taker(qty, price);
    const proceeds = qty * price - fee;
    const pnl = (price - pos.avgPrice) * qty - fee;
    p.cash += proceeds;
    p.realizedPnl += pnl;
    pos.qty -= qty;
    if (pos.qty <= 1e-9) p.positions = p.positions.filter(x => x.id !== positionId);
    p.trades.push({ id: 'trd_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7), side: 'sell', ticker: pos.ticker, topic: pos.topic, title: pos.title, qty, price, fee, pnl, at: Date.now() });
    save(p);
    return { ok: true, pnl, fee };
  }

  function mark(priceMap) {
    const p = load();
    for (const pos of p.positions) {
      const m = priceMap[pos.ticker];
      if (m != null) pos.lastMark = m;
    }
    save(p);
    return p;
  }

  function equity(priceMap) {
    const p = load();
    const px = priceMap || {};
    const openValue = p.positions.reduce((s, pos) => s + pos.qty * (px[pos.ticker] ?? pos.lastMark ?? pos.avgPrice), 0);
    return { equity: p.cash + openValue, cash: p.cash, openValue, realizedPnl: p.realizedPnl, unrealizedPnl: p.positions.reduce((s, pos) => s + (pos.qty * ((px[pos.ticker] ?? pos.lastMark ?? pos.avgPrice) - pos.avgPrice)), 0) };
  }

  function reset() { save(blank()); return load(); }

  return { load, buy, sell, mark, equity, reset, START_CASH };
})();
