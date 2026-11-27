// Pure, unit-testable core logic for the Kalshi Demo Desk (/live/).
// Mirrors kalshi_engine/simulator.py & kalshi_engine/kalshi_v2_client.py against official docs.kalshi.com specs.

export const ALLOWED_TOPICS = ["Elections", "Golf", "Culture", "Crypto", "Gas Prices"];

export const BUILTIN_STRATEGIES = {
  momentum_breakout: {
    id: "momentum_breakout",
    label: "Momentum Breakout",
    trade_type: "breakout_momentum",
    description: "Buys YES on >=+$0.10 jump or NO on <=-$0.10 drop when price is in [$0.12, $0.88]."
  },
  mean_reversion_fade: {
    id: "mean_reversion_fade",
    label: "Mean-Reversion Fade",
    trade_type: "mean_reversion",
    description: "Fades sharp >=$0.10 overextensions (buys NO on jump >=$0.60, buys YES on drop <=$0.40)."
  },
  high_roi_selective: {
    id: "high_roi_selective",
    label: "Selective High-ROI Model",
    trade_type: "selective_value",
    description: "Executes only alerts passing the Selective High-ROI chat (net_roi >= 12%, spread <= $0.08, depth >= 25)."
  },
  favorite_compounder: {
    id: "favorite_compounder",
    label: "Favorite Compounder",
    trade_type: "tail_convexity",
    description: "Accumulates high-probability contracts ($0.62-$0.92) on >=$0.10 confirmation."
  },
  longshot_asymmetric: {
    id: "longshot_asymmetric",
    label: "Longshot Asymmetric",
    trade_type: "tail_convexity",
    description: "Takes capped asymmetric convexity in [$0.05, $0.25] when upward >=$0.10 momentum triggers."
  }
};

/**
 * Official Kalshi 6-decimal-place raw fee ceiling per:
 * https://docs.kalshi.com/getting_started/fee_rounding.md
 * Scaled by `series.fee_multiplier` (1.0 standard, 0.5 reduced, 0 zero-fee).
 */
export function rawTakerFee6dp(contracts, price, rate = 0.07, feeMultiplier = 1) {
  const c = Number(contracts);
  const p = Number(price);
  const mult = Number(feeMultiplier ?? 1);
  if (!(c > 0) || p <= 0 || p >= 1 || !(mult > 0)) return 0;
  const scaled = Number((rate * mult * c * p * (1 - p) * 1e6).toPrecision(12));
  return Math.ceil(scaled - 1e-9) / 1e6;
}

/**
 * Per-order fee rounding accumulator ($0.0001 step for direct exchange, $0.01 for non-direct).
 */
export function applyFeeAccumulator(raw6dp, prevAccumulator = 0, directExchange = true) {
  const step = directExchange ? 0.0001 : 0.01;
  const total = raw6dp + prevAccumulator;
  const overageUnits = Math.ceil(total / step - 1e-12);
  const charged = Number((overageUnits * step).toFixed(6));
  const nextAcc = Number((total - charged).toFixed(6));
  return { raw6dp, charged, nextAccumulator: nextAcc };
}

/**
 * Normalize Kalshi V2 reciprocal orderbook (`orderbook_fp.yes_dollars` & `no_dollars` sorted ascending).
 * Best bid is the LAST element `[-1]`; implied YES asks derive from `$1.00 - no_bid` without truncating asymmetric sides.
 * Source: https://docs.kalshi.com/getting_started/orderbook_responses.md
 */
export function normalizeOrderbook(book, fallbackMarket = null) {
  const rawYes = Array.isArray(book?.yes_dollars) ? book.yes_dollars : [];
  const rawNo = Array.isArray(book?.no_dollars) ? book.no_dollars : [];

  let yesBids = rawYes
    .map(([p, q]) => ({ price: Number(p), size: Number(q) }))
    .filter((r) => r.price > 0 && r.size > 0)
    .sort((a, b) => b.price - a.price);

  let yesAsks = rawNo
    .map(([noBid, q]) => ({
      price: Number((1 - Number(noBid)).toFixed(4)),
      noBid: Number(noBid),
      size: Number(q)
    }))
    .filter((r) => r.price > 0 && r.price < 1 && r.size > 0)
    .sort((a, b) => a.price - b.price);

  let sourceType = "orderbook_fp";
  if (!yesBids.length && !yesAsks.length && fallbackMarket) {
    sourceType = "market_top_of_book";
    const yb = Number(fallbackMarket.yes_bid_dollars || 0);
    const ybs = Number(fallbackMarket.yes_bid_size_fp || 0);
    const ya = Number(fallbackMarket.yes_ask_dollars || 0);
    const yas = Number(fallbackMarket.yes_ask_size_fp || 0);
    if (yb > 0 && ybs > 0) yesBids = [{ price: yb, size: ybs }];
    if (ya > 0 && ya < 1 && yas > 0) yesAsks = [{ price: ya, noBid: Number((1 - ya).toFixed(4)), size: yas }];
  }

  const bestYesBid = yesBids.length ? yesBids[0].price : null;
  const bestYesAsk = yesAsks.length ? yesAsks[0].price : null;
  const spread = bestYesBid !== null && bestYesAsk !== null ? Number((bestYesAsk - bestYesBid).toFixed(4)) : null;

  return { yesBids, yesAsks, bestYesBid, bestYesAsk, spread, sourceType };
}

/**
 * Evaluate whether a price transition triggers a >=$0.10 swing alert and whether it passes the Selective High-ROI gate.
 */
export function evaluateSwing({ ticker, topic, title, prevPrice, newPrice, spread = 0.04, depthContracts = 50, ts, apiUrl, catalystLabel, catalystUrl }) {
  const prev = Number(prevPrice);
  const next = Number(newPrice);
  const delta = Number((next - prev).toFixed(4));
  if (Math.abs(delta) + 1e-9 < 0.10) return null;

  const direction = delta > 0 ? "up" : "down";
  const actionSide = delta > 0 ? "yes" : "no";
  const entry = actionSide === "yes" ? next : Number((1 - next).toFixed(4));
  const feePerContract = rawTakerFee6dp(1, Math.min(Math.max(entry, 0.01), 0.99));
  // Conservative fair-value impulse blend: partial continuation vs overreaction penalty on wide spread
  const fairEdge = Math.min(0.18, Math.abs(delta) * 0.55) - Math.max(0, Number(spread) - 0.03) * 0.8;
  const netProfit = fairEdge - feePerContract;
  const netRoiPct = entry > 0 ? Number(((netProfit / entry) * 100).toFixed(1)) : 0;

  const inBand = next >= 0.06 && next <= 0.94;
  const spreadOk = Number(spread) <= 0.08;
  const depthOk = Number(depthContracts) >= 25;
  const roiOk = netRoiPct >= 12.0;
  const selectivePass = Boolean(inBand && spreadOk && depthOk && roiOk);

  const reasons = [];
  if (!inBand) reasons.push(`price $${next.toFixed(4)} outside [$0.06, $0.94]`);
  if (!spreadOk) reasons.push(`spread $${Number(spread).toFixed(2)} > $0.08`);
  if (!depthOk) reasons.push(`depth ${Number(depthContracts).toFixed(0)} < 25`);
  if (!roiOk) reasons.push(`net ROI ${netRoiPct}% < 12.0%`);

  return {
    id: `sw-${ticker}-${ts || Date.now()}`,
    ts: ts || new Date().toISOString(),
    ticker,
    topic,
    title,
    prev_price: prev,
    new_price: next,
    delta,
    direction,
    spread: Number(spread),
    depth_contracts: Number(depthContracts),
    net_roi_pct: netRoiPct,
    selective_pass: selectivePass,
    selective_reason: selectivePass
      ? `Passes selective model: |Δ|=$${Math.abs(delta).toFixed(2)}, spread $${Number(spread).toFixed(2)}, depth ${Number(depthContracts).toFixed(0)}, net ROI +${netRoiPct}%.`
      : `Filtered out of High-ROI chat: ${reasons.join("; ")}.`,
    api_url: apiUrl,
    catalyst_label: catalystLabel,
    catalyst_url: catalystUrl
  };
}

/**
 * Decide trades generated by enabled built-in strategies + user custom strategies on a swing alert.
 */
export function generateStrategySignals(swing, enabledIds, customStrategies = []) {
  const signals = [];
  const p = Number(swing.new_price);
  const absDelta = Math.abs(Number(swing.delta));
  if (absDelta + 1e-9 < 0.10) return signals;

  if (enabledIds.includes("momentum_breakout") && p >= 0.12 && p <= 0.88) {
    signals.push({
      strategy_id: "momentum_breakout",
      strategy_label: BUILTIN_STRATEGIES.momentum_breakout.label,
      trade_type: BUILTIN_STRATEGIES.momentum_breakout.trade_type,
      side: swing.delta > 0 ? "yes" : "no",
      contracts: 15,
      price: swing.delta > 0 ? p : Number((1 - p).toFixed(4))
    });
  }

  if (enabledIds.includes("mean_reversion_fade")) {
    if (swing.delta > 0 && p >= 0.60 && p <= 0.95) {
      signals.push({
        strategy_id: "mean_reversion_fade",
        strategy_label: BUILTIN_STRATEGIES.mean_reversion_fade.label,
        trade_type: BUILTIN_STRATEGIES.mean_reversion_fade.trade_type,
        side: "no",
        contracts: 12,
        price: Number((1 - p).toFixed(4))
      });
    } else if (swing.delta < 0 && p >= 0.05 && p <= 0.40) {
      signals.push({
        strategy_id: "mean_reversion_fade",
        strategy_label: BUILTIN_STRATEGIES.mean_reversion_fade.label,
        trade_type: BUILTIN_STRATEGIES.mean_reversion_fade.trade_type,
        side: "yes",
        contracts: 12,
        price: p
      });
    }
  }

  if (enabledIds.includes("high_roi_selective") && swing.selective_pass) {
    signals.push({
      strategy_id: "high_roi_selective",
      strategy_label: BUILTIN_STRATEGIES.high_roi_selective.label,
      trade_type: BUILTIN_STRATEGIES.high_roi_selective.trade_type,
      side: swing.delta > 0 ? "yes" : "no",
      contracts: 20,
      price: swing.delta > 0 ? p : Number((1 - p).toFixed(4))
    });
  }

  if (enabledIds.includes("favorite_compounder") && p >= 0.62 && p <= 0.92 && swing.delta > 0) {
    signals.push({
      strategy_id: "favorite_compounder",
      strategy_label: BUILTIN_STRATEGIES.favorite_compounder.label,
      trade_type: BUILTIN_STRATEGIES.favorite_compounder.trade_type,
      side: "yes",
      contracts: 10,
      price: p
    });
  }

  if (enabledIds.includes("longshot_asymmetric") && p >= 0.05 && p <= 0.25 && swing.delta > 0) {
    signals.push({
      strategy_id: "longshot_asymmetric",
      strategy_label: BUILTIN_STRATEGIES.longshot_asymmetric.label,
      trade_type: BUILTIN_STRATEGIES.longshot_asymmetric.trade_type,
      side: "yes",
      contracts: 25,
      price: p
    });
  }

  for (const cs of customStrategies) {
    if (cs.enabled === false) continue;
    const minDelta = Number(cs.min_abs_delta ?? 0.10);
    const minPrice = Number(cs.min_price ?? 0.01);
    const maxPrice = Number(cs.max_price ?? 0.99);
    if (absDelta + 1e-9 < minDelta) continue;
    if (p < minPrice || p > maxPrice) continue;
    if (cs.direction && cs.direction !== "any" && cs.direction !== swing.direction) continue;
    if (cs.topic && cs.topic !== "any" && cs.topic !== swing.topic) continue;
    const side = cs.side === "no" ? "no" : cs.side === "fade" ? (swing.delta > 0 ? "no" : "yes") : cs.side === "follow" ? (swing.delta > 0 ? "yes" : "no") : "yes";
    signals.push({
      strategy_id: cs.id,
      strategy_label: cs.name || cs.id,
      trade_type: cs.trade_type || "custom_rule",
      side,
      contracts: Math.max(1, Number(cs.contracts || 10)),
      price: side === "yes" ? p : Number((1 - p).toFixed(4))
    });
  }

  return signals;
}

/**
 * Compute per-contract payout on a finalized Kalshi market (`yes`, `no`, or `scalar` with `settlement_value_dollars`).
 */
export function settlementPayoutPerContract(side, result, settlementValueDollars = null) {
  const normSide = String(side).toLowerCase();
  const normRes = String(result).toLowerCase();
  let yesPayout = 0;
  if (normRes === "yes") {
    yesPayout = 1.0;
  } else if (normRes === "no") {
    yesPayout = 0.0;
  } else if (normRes === "scalar") {
    const sv = Number(settlementValueDollars);
    if (!Number.isFinite(sv) || sv < 0 || sv > 1) {
      throw new Error(`Invalid scalar settlement_value_dollars: ${settlementValueDollars}`);
    }
    yesPayout = sv;
  } else {
    throw new Error(`Unsupported market result: ${result}`);
  }
  return normSide === "yes" ? yesPayout : Number((1 - yesPayout).toFixed(4));
}

/**
 * Compute depth-weighted VWAP fill price, slippage vs top-of-book, and 6dp taker fee
 * across a normalized reciprocal Kalshi `orderbook_fp` (`normalizeOrderbook` output).
 */
export function estimateOrderSlippage(normBook, side = "yes", contracts = 10, feeMultiplier = 1) {
  const req = Math.max(0, Number(contracts) || 0);
  if (req === 0 || !normBook) {
    return {
      requestedContracts: req,
      filledContracts: 0,
      unfilledContracts: req,
      topPrice: null,
      vwapPrice: null,
      slippageDollars: null,
      feeCharged: 0
    };
  }
  const normSide = String(side).toLowerCase();
  // Buying YES sweeps implied YES asks (derived from NO bids); buying NO sweeps implied NO asks (1 - YES bids).
  const ladder =
    normSide === "yes"
      ? normBook.yesAsks || []
      : (normBook.yesBids || []).map((lvl) => ({
          price: Number((1 - lvl.price).toFixed(4)),
          size: lvl.size
        }));

  if (!ladder.length) {
    return {
      requestedContracts: req,
      filledContracts: 0,
      unfilledContracts: req,
      topPrice: null,
      vwapPrice: null,
      slippageDollars: null,
      feeCharged: 0
    };
  }

  const topPrice = ladder[0].price;
  let remaining = req;
  let notional = 0;
  let filled = 0;
  let acc = 0;
  let totalChargedFee = 0;

  for (const lvl of ladder) {
    if (remaining <= 0) break;
    const take = Math.min(remaining, Number(lvl.size) || 0);
    if (take <= 0) continue;
    notional += take * lvl.price;
    filled += take;
    remaining -= take;
    const rawFee = rawTakerFee6dp(take, lvl.price, 0.07, feeMultiplier);
    const rounded = applyFeeAccumulator(rawFee, acc, true);
    totalChargedFee += rounded.charged;
    acc = rounded.nextAccumulator;
  }

  const vwapPrice = filled > 0 ? Number((notional / filled).toFixed(4)) : null;
  const slippageDollars = vwapPrice != null ? Number((vwapPrice - topPrice).toFixed(4)) : null;
  return {
    requestedContracts: req,
    filledContracts: Number(filled.toFixed(2)),
    unfilledContracts: Number(remaining.toFixed(2)),
    topPrice,
    vwapPrice,
    slippageDollars,
    feeCharged: Number(totalChargedFee.toFixed(4))
  };
}

