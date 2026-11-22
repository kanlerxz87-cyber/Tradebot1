// Kalshi's published trading-fee formula, used to charge simulated fills.
//
// Source (official fee schedule PDF, "Trading Fees", effective 2026-07-07):
//   fees = round up ( M x 0.07 x C x P x (1 - P) )
//   P  = price of a contract in dollars
//   C  = number of contracts traded
//   M  = per-contract multiplier (default 1 unless the schedule says otherwise)
//   round up = "rounds up such that the fee + positionCost is rounded to a centicent"
// https://kalshi.com/docs/kalshi-fee-schedule.pdf
//
// AUDIT NOTE (2026-11-22). An earlier version of this file carried a flag (F-02)
// saying the $0.01 row of the schedule's own table could not be reproduced. That
// was a misreading of the table: it has FOUR columns -
//
//   | Price of 1 contract | Fee for 1 contract | Price for 100 contracts | Fee for 100 contracts |
//   | $0.01               | $0.01              | $1.00                   | $0.07                 |
//
// The "$1.00" on that row is the price of 100 contracts, not a fee. The fee is
// $0.07, and 0.07 x 100 x 0.01 x 0.99 = 0.0693 rounds up to $0.07 like every
// other row. All 21 rows now reproduce, in both fee columns, and the whole table
// is asserted by tests/fees.test.mjs. See docs/audit/ item AUD-05.
//
// ROUNDING CAVEAT (kept honest, not fixed here). Rounding to the whole cent is
// what reproduces the printed table, but it is not the exchange's per-fill rule:
// docs.kalshi.com/getting_started/fee_rounding says the trade fee is rounded up to
// $0.000001 and the balance is then aligned to $0.0001 (direct members). For a
// direct member this model therefore overstates a fill's fee by up to $0.01. The
// difference is disclosed on docs/audit/ (AUD-04) rather than silently changed,
// because it also changes every historical P&L figure on the board.
export const FEE_SOURCE = 'https://kalshi.com/docs/kalshi-fee-schedule.pdf';
export const ROUNDING_SOURCE = 'https://docs.kalshi.com/getting_started/fee_rounding';

export const TAKER_RATE = 0.07;
export const MAKER_RATE = 0.0175;

/** Round a dollar amount up to the nearest $0.0001 (the exchange's centicent). */
export function roundUpCenticent(value) {
  const cents = Math.ceil(value * 10000 - 1e-9) / 10000;
  return cents === 0 ? 0 : cents;
}

/** Round a dollar amount up to the nearest whole cent, as the published table does. */
export function roundUpCent(value) {
  const cents = Math.ceil(value * 100 - 1e-9) / 100;
  return cents === 0 ? 0 : cents;
}

/**
 * Taker fee for `count` contracts at `price` (0-1 dollars).
 * Rounded up to the whole cent, which is the rule that reproduces the
 * published fee table (see the note above). Returns dollars.
 */
export function takerFee(count, price, multiplier = 1) {
  const p = clampPrice(price);
  const n = Number(count);
  if (!Number.isFinite(n) || n < 0) throw new Error(`bad count: ${count}`);
  if (n === 0) return 0;
  return roundUpCent(multiplier * TAKER_RATE * n * p * (1 - p));
}

export function makerFee(count, price, multiplier = 1) {
  const p = clampPrice(price);
  const n = Number(count);
  if (!Number.isFinite(n) || n < 0) throw new Error(`bad count: ${count}`);
  if (n === 0) return 0;
  return roundUpCent(multiplier * MAKER_RATE * n * p * (1 - p));
}

function clampPrice(price) {
  const p = Number(price);
  if (!Number.isFinite(p)) throw new Error(`bad price: ${price}`);
  return Math.min(1, Math.max(0, p));
}

/**
 * The fee schedule's own table: [price, fee for 1 contract, fee for 100 contracts].
 * Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf (effective 2026-07-07).
 * All 21 rows are reproducible and asserted by tests; see the AUDIT NOTE above.
 */
export const PUBLISHED_FEE_TABLE = [
  [0.01, 0.01, 0.07], [0.05, 0.01, 0.34], [0.10, 0.01, 0.63], [0.15, 0.01, 0.90],
  [0.20, 0.02, 1.12], [0.25, 0.02, 1.32], [0.30, 0.02, 1.47], [0.35, 0.02, 1.60],
  [0.40, 0.02, 1.68], [0.45, 0.02, 1.74], [0.50, 0.02, 1.75], [0.55, 0.02, 1.74],
  [0.60, 0.02, 1.68], [0.65, 0.02, 1.60], [0.70, 0.02, 1.47], [0.75, 0.02, 1.32],
  [0.80, 0.02, 1.12], [0.85, 0.01, 0.90], [0.90, 0.01, 0.63], [0.95, 0.01, 0.34],
  [0.99, 0.01, 0.07],
];
