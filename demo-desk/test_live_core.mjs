import test from "node:test";
import assert from "node:assert/strict";
import {
  ALLOWED_TOPICS,
  rawTakerFee6dp,
  applyFeeAccumulator,
  normalizeOrderbook,
  evaluateSwing,
  generateStrategySignals,
  settlementPayoutPerContract,
  estimateOrderSlippage
} from "./assets/live-core.mjs";

test("strictly 5 allowed topics", () => {
  assert.deepEqual(
    [...ALLOWED_TOPICS].sort(),
    ["Crypto", "Culture", "Elections", "Gas Prices", "Golf"]
  );
});

test("official 6dp fee rounding and subpenny accumulator match docs.kalshi.com/getting_started/fee_rounding.md", () => {
  // Official worked example: 1 contract @ $0.05 -> 0.07 * 1 * 0.05 * 0.95 = 0.003325
  const raw = rawTakerFee6dp(1, 0.05);
  assert.equal(raw, 0.003325);
  const f1 = applyFeeAccumulator(raw, 0, true);
  assert.equal(f1.charged, 0.0034);
  assert.equal(f1.nextAccumulator, -0.000075);

  // Fill 2 (2 contracts @ $0.05 -> raw 0.006650 + (-0.000075) = 0.006575 -> charged 0.0066, acc -0.000025)
  const raw2 = rawTakerFee6dp(2, 0.05);
  const f2 = applyFeeAccumulator(raw2, f1.nextAccumulator, true);
  assert.equal(f2.charged, 0.0066);
  assert.equal(f2.nextAccumulator, -0.000025);
});

test("reciprocal orderbook sorts best bid first and never truncates longer no_dollars side", () => {
  const norm = normalizeOrderbook({
    yes_dollars: [["0.0100", "10.00"]],
    no_dollars: [["0.0400", "20.00"], ["0.0800", "35.00"]]
  });
  assert.equal(norm.bestYesBid, 0.01);
  // Best NO bid is 0.08 -> implied best YES ask is $1.00 - $0.08 = $0.92 (size 35), plus $0.96 (size 20)
  assert.equal(norm.yesAsks.length, 2);
  assert.equal(norm.bestYesAsk, 0.92);
  assert.equal(norm.spread, 0.91);
});

test("swing detector enforces >=$0.10 threshold and selective high-ROI filter", () => {
  assert.equal(
    evaluateSwing({ ticker: "T1", topic: "Crypto", title: "x", prevPrice: 0.50, newPrice: 0.59 }),
    null
  );
  const pass = evaluateSwing({
    ticker: "KXDEMOFUTHOURLY-26NOV22H08-UP",
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
    ticker: "KXDEMOFUTHOURLY-26NOV22H08-UP",
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
    ticker: "KXDEMOFUTHOURLY-26NOV22H08-UP",
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
  // momentum_breakout, mean_reversion_fade (p=0.65 >= 0.60), high_roi_selective, favorite_compounder (0.65 in [0.62,0.92]), + custom cs1 = 5 signals
  assert.equal(sigs.length, 5);

  assert.equal(settlementPayoutPerContract("yes", "yes"), 1.0);
  assert.equal(settlementPayoutPerContract("yes", "no"), 0.0);
  assert.equal(settlementPayoutPerContract("yes", "scalar", "0.5000"), 0.5);
  assert.equal(settlementPayoutPerContract("no", "scalar", "0.5000"), 0.5);
});

test("series fee_multiplier scales 6dp fee and estimateOrderSlippage computes multi-level VWAP", () => {
  assert.equal(rawTakerFee6dp(10, 0.5, 0.07, 1), 0.175);
  assert.equal(rawTakerFee6dp(10, 0.5, 0.07, 0.5), 0.0875);
  assert.equal(rawTakerFee6dp(10, 0.5, 0.07, 0), 0);

  const norm = normalizeOrderbook({
    yes_dollars: [["0.1600", "50.00"], ["0.1700", "20.00"]],
    no_dollars: [["0.8100", "30.00"], ["0.8200", "10.00"]]
  });
  // Implied YES asks: $0.18 (size 10), then $0.19 (size 30).
  // Buying 25 YES takes 10 @ $0.18 + 15 @ $0.19 = $4.65 / 25 = $0.1860 VWAP (+$0.0060 slippage).
  const slip = estimateOrderSlippage(norm, "yes", 25, 1);
  assert.equal(slip.filledContracts, 25);
  assert.equal(slip.unfilledContracts, 0);
  assert.equal(slip.topPrice, 0.18);
  assert.equal(slip.vwapPrice, 0.186);
  assert.equal(slip.slippageDollars, 0.006);
  assert.ok(slip.feeCharged > 0);
});

