// Pure, unit-testable core logic for the Kalshi Demo Desk (/demo-desk/).
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

function toScaledBigInt(val, scaleDigits = 6) {
  const str = String(val ?? "0").trim();
  if (!str || str === "NaN") return 0n;
  const neg = str.startsWith("-");
  const clean = neg ? str.slice(1) : str.startsWith("+") ? str.slice(1) : str;
  const [intPart = "0", fracPart = ""] = clean.split(".");
  const padded = (fracPart + "0".repeat(scaleDigits)).slice(0, scaleDigits);
  const bi = BigInt(intPart || "0") * 10n ** BigInt(scaleDigits) + BigInt(padded || "0");
  return neg ? -bi : bi;
}

/**
 * Official Kalshi 6-decimal-place raw fee ceiling per:
 * https://docs.kalshi.com/getting_started/fee_rounding
 * Computed via exact BigInt fixed-point arithmetic (zero IEEE-754 binary float drift!).
 * Supports per-series `feeMultiplier` (1, 0.5, 0 from GET /series/{ticker})
 * and taker (0.07) vs maker (0.0175) base rates.
 */
export function rawTakerFee6dp(contracts, price, rate = 0.07, feeMultiplier = 1) {
  const cNum = Number(contracts);
  const pNum = Number(price);
  const mNum = Number(feeMultiplier);
  const rNum = Number(rate);
  if (!(cNum > 0) || pNum <= 0 || pNum >= 1 || !(mNum > 0) || !(rNum > 0)) return 0;

  // Scale each factor by 10^6 -> product is scaled by 10^24; divide by 10^18 with exact ceiling to get microdollars (10^6).
  const r6 = toScaledBigInt(rNum.toFixed(6), 6);
  const m6 = toScaledBigInt(mNum.toFixed(6), 6);
  const c6 = toScaledBigInt(cNum.toFixed(6), 6);
  const p6 = toScaledBigInt(pNum.toFixed(6), 6);
  const q6 = 1_000_000n - p6;
  const prod24 = r6 * m6 * c6 * p6 * q6; // scaled by 10^30
  const denom = 10n ** 24n; // leaves 10^6 (microdollars)
  const ceilMicro = (prod24 + denom - 1n) / denom;
  return Number(ceilMicro) / 1e6;
}

/**
 * Official Kalshi 5-step per-order fee rounding accumulator & rebate in integer microdollars ($0.000001):
 *   1. unaligned_change = signed_revenue - trade_fee
 *   2. aligned_change   = floor(unaligned_change / step) * step
 *   3. rounding_fee     = unaligned_change - aligned_change   (always >= 0)
 *   4. acc              = prev_accumulator + rounding_fee     (always >= 0)
 *   5. rebate           = min(floor(acc / step) * step, trade_fee + rounding_fee)
 * Source: https://docs.kalshi.com/getting_started/fee_rounding
 */
export function applyFeeAccumulator(raw6dp, prevAccumulator = 0, directExchange = true, signedRevenue = 0) {
  const stepMicro = directExchange ? 100 : 10000; // $0.0001 vs $0.01 in microdollars
  const tradeFeeMicro = Math.max(0, Math.round(Number(raw6dp || 0) * 1e6));
  const prevAccMicro = Math.max(0, Math.round(Number(prevAccumulator || 0) * 1e6));
  const revMicro = Math.round(Number(signedRevenue || 0) * 1e6);

  const unalignedMicro = revMicro - tradeFeeMicro;
  const alignedMicro = Math.floor(unalignedMicro / stepMicro) * stepMicro;
  const roundingFeeMicro = unalignedMicro - alignedMicro;

  const grossFeeMicro = tradeFeeMicro + roundingFeeMicro;
  const accBeforeRebate = prevAccMicro + roundingFeeMicro;
  const maxRebateUnits = Math.floor(accBeforeRebate / stepMicro);
  const rebateMicro = Math.min(maxRebateUnits * stepMicro, grossFeeMicro);

  const nextAccMicro = accBeforeRebate - rebateMicro;
  const chargedMicro = Math.max(0, grossFeeMicro - rebateMicro);

  return {
    raw6dp: Number((tradeFeeMicro / 1e6).toFixed(6)),
    roundingFee: Number((roundingFeeMicro / 1e6).toFixed(6)),
    rebate: Number((rebateMicro / 1e6).toFixed(6)),
    charged: Number((chargedMicro / 1e6).toFixed(6)),
    nextAccumulator: Number((nextAccMicro / 1e6).toFixed(6))
  };
}

/**
 * Normalize Kalshi V2 reciprocal orderbook (`orderbook_fp.yes_dollars` & `no_dollars` sorted ascending).
 * Best bid is the LAST element `[-1]`; implied YES asks derive from `$1.00 - no_bid` without truncating asymmetric sides.
 * Source: https://docs.kalshi.com/getting_started/orderbook_responses
 */
export function normalizeOrderbook(book, fallbackMarket = null) {
  const rawYes = Array.isArray(book?.yes_dollars) ? book.yes_dollars : [];
  const rawNo = Array.isArray(book?.no_dollars) ? book.no_dollars : [];

  let yesBids = rawYes
    .map(([p, q]) => ({ price: Number(p), size: Number(q) }))
    .filter((r) => r.price > 0 && r.size > 0)
    .sort((a, b) => b.price - a.price);

  const noBids = rawNo
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

  let noAsks = rawYes
    .map(([yesBid, q]) => ({
      price: Number((1 - Number(yesBid)).toFixed(4)),
      yesBid: Number(yesBid),
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
    if (yb > 0 && ybs > 0) {
      yesBids = [{ price: yb, size: ybs }];
      noAsks = [{ price: Number((1 - yb).toFixed(4)), yesBid: yb, size: ybs }];
    }
    if (ya > 0 && ya < 1 && yas > 0) {
      yesAsks = [{ price: ya, noBid: Number((1 - ya).toFixed(4)), size: yas }];
    }
  }

  const bestYesBid = yesBids.length ? yesBids[0].price : null;
  const bestYesAsk = yesAsks.length ? yesAsks[0].price : null;
  const bestNoBid = noBids.length ? noBids[0].price : null;
  const bestNoAsk = noAsks.length ? noAsks[0].price : null;
  const spread = bestYesBid !== null && bestYesAsk !== null ? Number((bestYesAsk - bestYesBid).toFixed(4)) : null;

  return { yesBids, noBids, yesAsks, noAsks, bestYesBid, bestYesAsk, bestNoBid, bestNoAsk, spread, sourceType };
}

/**
 * Walk executable asks ascending for a BUY order to compute VWAP fill price, depth, and slippage.
 */
export function estimateOrderbookFill(normBook, side = "yes", contracts = 10) {
  const normSide = String(side).toLowerCase() === "no" ? "no" : "yes";
  const ladder = normSide === "yes" ? normBook?.yesAsks || [] : normBook?.noAsks || [];
  const requested = Math.max(0, Number(contracts || 0));
  let remaining = requested;
  let filled = 0;
  let notional = 0;
  let worstPrice = null;
  let levelsWalked = 0;
  const totalDepth = Number(ladder.reduce((s, lv) => s + Number(lv.size || 0), 0).toFixed(2));

  for (const lv of ladder) {
    if (remaining <= 1e-9) break;
    const sz = Number(lv.size || 0);
    const px = Number(lv.price || 0);
    if (!(sz > 0) || !(px > 0)) continue;
    const take = Math.min(remaining, sz);
    filled += take;
    notional += take * px;
    remaining -= take;
    worstPrice = px;
    levelsWalked += 1;
  }

  const bestAsk = ladder.length ? ladder[0].price : null;
  const vwapPrice = filled > 0 ? Number((notional / filled).toFixed(4)) : null;
  const slippage = vwapPrice !== null && bestAsk !== null ? Number((vwapPrice - bestAsk).toFixed(4)) : null;

  return {
    side: normSide,
    requestedContracts: Number(requested.toFixed(2)),
    filledContracts: Number(filled.toFixed(2)),
    unfilledContracts: Number(Math.max(0, remaining).toFixed(2)),
    bestAsk,
    vwapPrice,
    worstPrice,
    slippage,
    levelsWalked,
    totalDepth
  };
}

/**
 * Evaluate whether a price transition triggers a >=$0.10 swing alert and whether it passes the Selective High-ROI gate.
 */
export function evaluateSwing({
  ticker,
  topic,
  title,
  prevPrice,
  newPrice,
  spread = 0.04,
  depthContracts = 50,
  feeMultiplier = 1,
  ts,
  apiUrl,
  catalystLabel,
  catalystUrl
}) {
  const prev = Number(prevPrice);
  const next = Number(newPrice);
  const delta = Number((next - prev).toFixed(4));
  if (Math.abs(delta) + 1e-9 < 0.10) return null;

  const direction = delta > 0 ? "up" : "down";
  const actionSide = delta > 0 ? "yes" : "no";
  const entry = actionSide === "yes" ? next : Number((1 - next).toFixed(4));
  const feePerContract = rawTakerFee6dp(1, Math.min(Math.max(entry, 0.01), 0.99), 0.07, feeMultiplier);
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
    const side =
      cs.side === "no"
        ? "no"
        : cs.side === "fade"
        ? swing.delta > 0
          ? "no"
          : "yes"
        : cs.side === "follow"
        ? swing.delta > 0
          ? "yes"
          : "no"
        : "yes";
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
