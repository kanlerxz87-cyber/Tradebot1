// Kalshi's published trading-fee formula, used to charge simulated fills.
//
// Source (official fee schedule PDF, "Trading Fees"):
//   fees = round up ( M x 0.07 x C x P x (1 - P) )
//   P  = price of a contract in dollars
//   C  = number of contracts traded
//   M  = per-contract multiplier (default 1 unless the schedule says otherwise)
//   round up = "rounds up such that the fee + positionCost is rounded to a centicent"
// https://kalshi.com/docs/kalshi-fee-schedule.pdf
//
// VERIFICATION NOTE (flag F-02). The formula alone, rounded up to $0.0001,
// does NOT reproduce the schedule's own summary table: at $0.01 the formula
// gives $0.0007, while the table prints $0.01. Rounding the formula's result up
// to the whole cent reproduces 20 of the 21 rows exactly, both the 1-contract
// and the 100-contract column:
//
//   $0.05 -> $0.01 / $0.34      $0.50 -> $0.02 / $1.75
//   $0.20 -> $0.02 / $1.12      $0.99 -> $0.01 / $0.07
//
// The one row that does not reproduce is $0.01, and the PDF's own text layer
// for that row is internally inconsistent (its 100-contract fee reads "$1.00",
// which is the price column, not a fee). The whole-cent rule is therefore what
// this model charges, and the single unreproducible row is flagged rather than
// silently special-cased. Tests assert the 20 reproducible rows.

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
 * Source: https://kalshi.com/docs/kalshi-fee-schedule.pdf
 * The $0.01 row's printed 100-contract value is not reproducible from the PDF
 * text and is excluded (flag F-02); every other row is asserted by tests.
 */
export const PUBLISHED_FEE_TABLE = [
  [0.01, 0.01, null], [0.05, 0.01, 0.34], [0.10, 0.01, 0.63], [0.15, 0.01, 0.90],
  [0.20, 0.02, 1.12], [0.25, 0.02, 1.32], [0.30, 0.02, 1.47], [0.35, 0.02, 1.60],
  [0.40, 0.02, 1.68], [0.45, 0.02, 1.74], [0.50, 0.02, 1.75], [0.55, 0.02, 1.74],
  [0.60, 0.02, 1.68], [0.65, 0.02, 1.60], [0.70, 0.02, 1.47], [0.75, 0.02, 1.32],
  [0.80, 0.02, 1.12], [0.85, 0.01, 0.90], [0.90, 0.01, 0.63], [0.95, 0.01, 0.34],
  [0.99, 0.01, 0.07],
];
