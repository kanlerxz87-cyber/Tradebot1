/* model.js — the transparent high-ROI screen and the ≥ $0.10 swing alert engine.

   The score is a documented heuristic. It is NOT a prediction, NOT advice, and it
   has no measured edge: nothing in this repository has verified that a contract
   scoring 65 subsequently returned more than one scoring 40. It ranks what is on
   screen so a trader can look at the most liquid, tightest, most-decisive markets
   first. Every input is a value the dashboard already fetched; no input is invented.

   Fixed 2026-11-27 (session 2573166c), each reproducing in terminal/tests/core.test.mjs:

     * the reference price never reset after an alert, so a market that sat $0.10
       away from where it started re-alerted on every poll and on every cooldown
       expiry. Only the cooldown masked it.
     * a quote that stopped updating (a market that stops trading keeps its last
       price, and the exchange serves cached quotes) was treated as a live movement.
     * a re-quote after a long gap (the popup closed, the laptop slept) was compared
       against an hour-old price and reported as a swing.
   */
'use strict';

const Model = {
  /* metrics: {
       volRank:        0..1  — rank of contract volume among visible markets (0 = highest)
       spread:         number — yes ask − yes bid, in dollars
       moveAbs:        number — absolute move in dollars
       price:          number — last/bid price, 0..1
       openInterest:   number — contracts
     }
     Returns 0..100. The weights are shown on the dashboard next to the score. */
  score(m, metrics) {
    let s = 30;
    const rank = metrics.volRank ?? 0.5;
    if (rank <= 0.10) s += 25; else if (rank <= 0.25) s += 18; else if (rank <= 0.5) s += 10;
    const sp = metrics.spread ?? 0.1;
    if (sp <= 0.03) s += 20; else if (sp <= 0.07) s += 12; else if (sp <= 0.12) s += 6;
    const mv = Math.abs(metrics.moveAbs ?? 0);
    if (mv >= 0.10) s += 15; else if (mv >= 0.05) s += 8;
    const px = metrics.price ?? 0.5;
    if (px >= 0.55 && px <= 0.85) s += 8; else if (px > 0.90) s += 2;
    if ((metrics.openInterest ?? 0) >= 50000) s += 7; else if ((metrics.openInterest ?? 0) >= 10000) s += 4;
    return Math.max(0, Math.min(100, Math.round(s)));
  },

  verdict(score) {
    if (score >= 75) return { label: 'STRONG — model-favored', cls: 'up' };
    if (score >= 65) return { label: 'Model-approved (high-ROI candidate)', cls: 'up' };
    if (score >= 50) return { label: 'Neutral', cls: 'flat' };
    return { label: 'Below model threshold', cls: 'down' };
  },

  /* Implied ROI if the YES side resolves at $1.00 — pure arithmetic on the price,
     before fees, ignoring the possibility that it does not resolve YES. Labelled
     "if YES" everywhere it is shown, because that is all it is. */
  impliedRoi(price) { return price && price > 0 ? (1 - price) / price : null; },

  MODEL_FEED_THRESHOLD: 65,
};

/* Ring-buffered alert engine with per-market cooldown.
   update() returns an alert object or null. `meta.stale` suppresses the movement
   entirely: a quote that has not changed because nobody is trading is not a swing. */
class AlertEngine {
  constructor(cooldownMs = 90000) {
    this.state = new Map();
    this.cooldownMs = cooldownMs;
    this.windowMs = 120000;            // intra-window detection
    this.historyMs = 10 * 60 * 1000;   // keep 10 minutes of points
    this.threshold = 0.10;             // dollars, inclusive
  }

  reset(key) { this.state.delete(key); }

  update(key, price, meta = {}) {
    if (price == null || !Number.isFinite(price)) return null;
    if (meta.stale) return null;

    const now = Number.isFinite(meta.now) ? meta.now : Date.now();
    let s = this.state.get(key);
    if (!s) {
      s = { ref: price, refTs: now, history: [[now, price]], lastAlertAt: 0 };
      this.state.set(key, s);
      return null;
    }
    /* A gap longer than the history window means the previous reference is not a
       reference any more. Rebase instead of comparing across the gap. */
    const lastTs = s.history[s.history.length - 1][0];
    if (now - lastTs > this.historyMs) {
      s.ref = price; s.refTs = now; s.history = [[now, price]]; s.lastAlertAt = 0;
      return null;
    }

    s.history.push([now, price]);
    while (s.history.length > 2 && now - s.history[0][0] > this.historyMs) s.history.shift();

    // Price ~windowMs ago (nearest point at or before target)
    const target = now - this.windowMs;
    let past = s.history[0][1];
    for (const [t, p] of s.history) { if (t <= target) past = p; else break; }

    const deltaSession = price - s.ref;
    const deltaWindow = price - past;

    let move = null, delta = 0;
    if (Math.abs(deltaSession) >= this.threshold - 1e-9) { move = 'session'; delta = deltaSession; }
    else if (Math.abs(deltaWindow) >= this.threshold - 1e-9) { move = 'window'; delta = deltaWindow; }

    if (move && now - s.lastAlertAt >= this.cooldownMs) {
      s.lastAlertAt = now;
      const from = move === 'session' ? s.ref : past;
      /* Reset the reference to the price that just alerted. The excursion is
         measured and reported once; the next alert needs another $0.10. */
      s.ref = price; s.refTs = now;
      s.history = [[now, price]];
      return {
        id: key + '_' + now,
        key, ticker: meta.ticker, title: meta.title, topic: meta.topic,
        price, delta, move,
        from_price: from,
        to_price: price,
        abs_delta: Math.abs(delta),
        direction: delta >= 0 ? 'up' : 'down',
        ts: now,
        ts_iso: new Date(now).toISOString(),
      };
    }
    return null;
  }

  snapshot(key) { return this.state.get(key) || null; }
}

/* Normalise one row of the server-collected swing log (terminal/data/alerts.json,
   written hourly by tools/terminal-collect.mjs). Returns null for anything that
   does not meet the rule, so a malformed log cannot produce a fake alert. */
function normaliseLoggedAlert(a) {
  if (!a || !a.ticker) return null;
  const abs = Number(a.abs_delta);
  if (!Number.isFinite(abs) || abs < 0.10 - 1e-9) return null;
  if (a.direction !== 'up' && a.direction !== 'down') return null;
  const to = Number(a.to_price), from = Number(a.from_price);
  return {
    id: String(a.id || `${a.ticker}_${a.to_ts}`),
    ticker: a.ticker,
    title: a.title || a.ticker,
    topic: a.topic || null,
    direction: a.direction,
    delta: a.direction === 'up' ? abs : -abs,
    abs_delta: abs,
    from_price: Number.isFinite(from) ? from : null,
    to_price: Number.isFinite(to) ? to : null,
    price: Number.isFinite(to) ? to : null,
    ts: Number(a.to_ts) || 0,
    ts_iso: a.to_iso || (a.to_ts ? new Date(Number(a.to_ts) * 1000).toISOString() : null),
    basis: a.basis || null,
    source_url: a.source_url || null,
    logged: true,
  };
}
