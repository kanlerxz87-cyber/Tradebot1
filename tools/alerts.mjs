// Swing detection and the "model likes this" research score.
//
// Two independent things live here:
//
// 1. ALERTS - an observed change of >= $0.10 in either direction on the
//    contract price of a tracked market. That threshold is the user's rule, not
//    a Kalshi definition. An alert says "the observed price moved";
//    it never says why.
//
// 2. The RESEARCH SCORE - a 0-100 heuristic used only to pick which alerts
//    appear in the second, filtered chat. It is a formula written for this
//    project. It is NOT a forecast of return, NOT Kalshi data, and must never
//    be described as "high ROI". The filtered chat is labelled
//    "model-filtered" everywhere it appears.

export const SWING_THRESHOLD = 0.1; // dollars, as specified: >= $0.10 either way
export const ALERT_RULE_SOURCE = 'https://docs.kalshi.com/getting_started/orderbook_responses';

export function round4(n) { return Math.round(n * 10000) / 10000; }
export function round2(n) { return Math.round(n * 100) / 100; }

/**
 * The mid-price of the YES contract, when both sides of the book exist.
 * Returns null when the book is one-sided - an absent bid is not a price of 0.
 */
export function yesMid(yesBid, yesAsk) {
  const bid = toPrice(yesBid);
  const ask = toPrice(yesAsk);
  if (bid == null || ask == null) return null;
  // An empty side is not a price, and either side alone is enough to disqualify the
  // pair: Kalshi quotes a side with no resting orders as a bid of 0.0000 or an ask
  // of 1.0000. A midpoint built from that sentinel is a phantom - a 14c bid against
  // an "ask" of $1.00 reads as 57c. All eight markets in this repository's own
  // committed demo capture (data/snapshot.json) have yesAsk 1.0 with an empty NO
  // book, so this is the common case, not an edge case.
  // Source: https://docs.kalshi.com/getting_started/orderbook_responses
  //   ("A YES BID at price X is equivalent to a NO ASK at (1 - X)"; a market with no
  //   resting orders returns empty arrays).
  if (bid <= 0 || ask >= 1) return null;
  return round4((bid + ask) / 2);
}

function toPrice(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Compare a fresh observation with the last observation of the same market.
 * Returns null when there is nothing comparable (no prior observation, or no
 * usable price on one of the two sides) - never fabricates a 0 change.
 */
export function detectSwing(previous, current) {
  if (!previous || !current) return null;
  if (previous.marketTicker !== current.marketTicker) return null;
  const from = previous.yesMid;
  const to = current.yesMid;
  if (from == null || to == null) return null;
  const delta = round4(to - from);
  return {
    delta,
    from,
    to,
    absDelta: round4(Math.abs(delta)),
    direction: delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat',
    qualifies: Math.abs(delta) >= SWING_THRESHOLD - 1e-9,
  };
}

/**
 * Research score, 0-100. Deterministic and explainable; every component is
 * shown in the UI so a reader can disagree with it.
 *
 * Components (all bounded, then scaled):
 *   move      0-40  how large the observed move is, saturating at 40c
 *   liquidity 0-25  resting contracts on the side you would have to cross
 *   tightness 0-15  narrower spread is better
 *   volume    0-10  24h volume, saturating at 500 contracts
 *   freshness 0-10  how recent the observation is
 *
 * A score is only computed when the inputs exist; a missing input contributes
 * zero AND is reported in `missing`, so a thin market cannot masquerade as a
 * good one.
 */
export function researchScore({ absDelta, crossDepthContracts, spread, volume24h, ageSeconds }) {
  const missing = [];
  const parts = {};

  if (Number.isFinite(absDelta)) {
    parts.move = clamp(absDelta / 0.4, 0, 1) * 40;
  } else { parts.move = 0; missing.push('move'); }

  if (Number.isFinite(crossDepthContracts) && crossDepthContracts > 0) {
    parts.liquidity = clamp(Math.log10(1 + crossDepthContracts) / Math.log10(1 + 5000), 0, 1) * 25;
  } else { parts.liquidity = 0; missing.push('liquidity'); }

  if (Number.isFinite(spread) && spread >= 0) {
    parts.tightness = clamp(1 - spread / 0.2, 0, 1) * 15;
  } else { parts.tightness = 0; missing.push('spread'); }

  if (Number.isFinite(volume24h) && volume24h >= 0) {
    parts.volume = clamp(Math.log10(1 + volume24h) / Math.log10(1 + 500), 0, 1) * 10;
  } else { parts.volume = 0; missing.push('volume'); }

  if (Number.isFinite(ageSeconds) && ageSeconds >= 0) {
    parts.freshness = clamp(1 - ageSeconds / 900, 0, 1) * 10;
  } else { parts.freshness = 0; missing.push('freshness'); }

  const score = Math.round(Object.values(parts).reduce((s, v) => s + v, 0));
  return {
    score: clamp(score, 0, 100),
    parts: Object.fromEntries(Object.entries(parts).map(([k, v]) => [k, round2(v)])),
    missing,
    // A market missing two or more inputs, or with no crossable depth, is not
    // eligible for the filtered feed however high the raw number is.
    eligible: missing.length < 2 && Number.isFinite(crossDepthContracts) && crossDepthContracts > 0,
  };
}

function clamp(n, lo, hi) { return Math.min(hi, Math.max(lo, n)); }

/**
 * Rank the filtered feed. Higher score first, then larger absolute move, then
 * the fresher observation. Pure function so it can be tested offline.
 */
export function rankForFilteredFeed(rows) {
  return [...rows].sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    if (b.absDelta !== a.absDelta) return b.absDelta - a.absDelta;
    return String(b.observedAt).localeCompare(String(a.observedAt));
  });
}

/**
 * A resolution row for a market: how it resolved, yes or no, or still open.
 * `result` is the exchange's field (docs: market_lifecycle). Scalar and empty
 * are distinguished from "not yet known".
 */
export function resolutionOf(market) {
  const status = market?.status ?? '';
  const result = market?.result ?? '';
  if (result === 'yes' || result === 'no') {
    return {
      state: status === 'finalized' ? 'resolved' : 'determined',
      result,
      label: result === 'yes' ? 'YES' : 'NO',
      final: status === 'finalized',
    };
  }
  if (result === 'scalar') return { state: 'scalar', result: 'scalar', label: 'Scalar (not binary)', final: status === 'finalized' };
  if (status === 'finalized') return { state: 'resolved', result: '', label: 'Finalized, result not published', final: true };
  if (['closed', 'determined', 'disputed', 'amended'].includes(status)) {
    return { state: 'awaiting', result: '', label: 'Awaiting result', final: false };
  }
  return { state: 'open', result: '', label: 'Trading', final: false };
}
