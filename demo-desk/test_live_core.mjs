import test from "node:test";
import assert from "node:assert/strict";
import {
  ALLOWED_TOPICS,
  rawTakerFee6dp,
  applyFeeAccumulator,
  normalizeOrderbook,
  estimateOrderbookFill,
  evaluateSwing,
  generateStrategySignals,
  settlementPayoutPerContract
} from "./assets/live-core.mjs";

test("strictly 5 allowed topics", () => {
  assert.deepEqual(
    [...ALLOWED_TOPICS].sort(),
    ["Crypto", "Culture", "Elections", "Gas Prices", "Golf"]
  );
});

test("official 6dp fee rounding, signed_revenue alignment, positive accumulator & series fee_multiplier match docs.kalshi.com/getting_started/fee_rounding", () => {
  // Worked example 1: 1 contract @ $0.05 -> 0.07 * 1 * 0.05 * 0.95 = 0.003325
  const raw = rawTakerFee6dp(1, 0.05);
  assert.equal(raw, 0.003325);
  const f1 = applyFeeAccumulator(raw, 0, true, -0.05);
  assert.equal(f1.charged, 0.0034);
  assert.equal(f1.roundingFee, 0.000075);
  assert.equal(f1.nextAccumulator, 0.000075); // non-negative overcharge credit!

  // Fill 2: 2 contracts @ $0.05 -> raw 0.006650, roundingFee 0.000050, acc 0.000125 >= 0.0001 -> $0.0001 rebate!
  const raw2 = rawTakerFee6dp(2, 0.05);
  const f2 = applyFeeAccumulator(raw2, f1.nextAccumulator, true, -0.10);
  assert.equal(f2.rebate, 0.0001);
  assert.equal(f2.charged, 0.0066);
  assert.equal(f2.nextAccumulator, 0.000025);

  // Worked example 2 ($0.055 deci-cent fill on non-direct $0.01 vs direct $0.0001):
  // raw = ceil_6dp(0.07 * 1 * 0.055 * 0.945) = ceil_6dp(0.00363825) = 0.003639
  const rawDeci = rawTakerFee6dp(1, 0.055);
  assert.equal(rawDeci, 0.003639);
  const nonDirect = applyFeeAccumulator(rawDeci, 0, false, -0.055);
  assert.equal(nonDirect.charged, 0.005); // total debit -$0.055 - $0.005 = -$0.0600 (exact cent alignment!)
  assert.equal(nonDirect.nextAccumulator, 0.001361);

  const direct = applyFeeAccumulator(rawDeci, 0, true, -0.055);
  assert.equal(direct.charged, 0.0037); // total debit -$0.055 - $0.0037 = -$0.0587 (exact $0.0001 alignment!)
  assert.equal(direct.nextAccumulator, 0.000061);

  // Per-series fee_multiplier = 0 and 0.5
  assert.equal(rawTakerFee6dp(100, 0.5, 0.07, 0), 0);
  assert.equal(rawTakerFee6dp(100, 0.5, 0.07, 0.5), 0.875);
});

test("reciprocal orderbook sorts best bid first, never truncates longer no_dollars side, and computes VWAP slippage", () => {
  const norm = normalizeOrderbook({
    yes_dollars: [["0.0100", "10.00"]],
    no_dollars: [["0.0400", "20.00"], ["0.0800", "35.00"]]
  });
  assert.equal(norm.bestYesBid, 0.01);
  // Best NO bid is 0.08 -> implied best YES ask is $1.00 - $0.08 = $0.92 (size 35), plus $0.96 (size 20)
  assert.equal(norm.yesAsks.length, 2);
  assert.equal(norm.bestYesAsk, 0.92);
  assert.equal(norm.spread, 0.91);

  const fill50 = estimateOrderbookFill(norm, "yes", 50);
  assert.equal(fill50.filledContracts, 50);
  assert.equal(fill50.levelsWalked, 2);
  assert.equal(fill50.vwapPrice, Number(((35 * 0.92 + 15 * 0.96) / 50).toFixed(4)));
  assert.ok(fill50.slippage > 0);
});

test("swing detector enforces >=$0.10 threshold and selective high-ROI filter", () => {
  assert.equal(
    evaluateSwing({ ticker: "T1", topic: "Crypto", title: "x", prevPrice: 0.50, newPrice: 0.59 }),
    null
  );
  const pass = evaluateSwing({
    ticker: "KXDEMOFUTHOURLY-26NOV27H20-UP",
    topic: "Crypto",
    title: "BTC Hourly",
    prevPrice: 0.35,
    newPrice: 0.65,
    spread: 0.04,
    depthContracts: 865.34
  });
  assert.ok(pass);
  assert.equal(pass.selective_pass, true);

  const reject = evaluateSwing({
    ticker: "KXDEMOFUTHOURLY-26NOV27H20-UP",
    topic: "Crypto",
    title: "BTC Hourly",
    prevPrice: 0.65,
    newPrice: 0.55,
    spread: 0.98,
    depthContracts: 865.34
  });
  assert.ok(reject);
  assert.equal(reject.selective_pass, false);
});

test("all 5 built-in strategies and custom strategies generate categorized signals; yes/no/scalar settlement works", () => {
  const swUp = evaluateSwing({
    ticker: "KXDEMOFUTHOURLY-26NOV27H20-UP",
    topic: "Crypto",
    title: "BTC Hourly",
    prevPrice: 0.35,
    newPrice: 0.65,
    spread: 0.04,
    depthContracts: 865.34
  });
  const sigs = generateStrategySignals(
    swUp,
    ["momentum_breakout", "mean_reversion_fade", "high_roi_selective", "favorite_compounder", "longshot_asymmetric"],
    [{ id: "cs1", name: "Custom", trade_type: "custom_rule", topic: "Crypto", direction: "up", side: "follow", min_abs_delta: 0.10, min_price: 0.2, max_price: 0.8, contracts: 7 }]
  );
  assert.equal(sigs.length, 5);

  assert.equal(settlementPayoutPerContract("yes", "yes"), 1.0);
  assert.equal(settlementPayoutPerContract("yes", "no"), 0.0);
  assert.equal(settlementPayoutPerContract("yes", "scalar", "0.5000"), 0.5);
  assert.equal(settlementPayoutPerContract("no", "scalar", "0.5000"), 0.5);
});
