/* model.js — transparent high-ROI screening model + $0.10 swing alert engine.
   The score is a documented heuristic, NOT financial advice and NOT a prediction.
   All components are computed from values the dashboard already fetched. */
'use strict';

const Model = {
  /* metrics: {
       volRank:        0..1  — rank of contract volume among visible markets (0 = highest)
       spread:         number — yes ask − yes bid, in dollars
       moveAbs:        number — absolute session move, dollars
       price:          number — last/bid price, 0..1
       openInterest:   number — contracts
     }
     Returns 0..100. */
  score(m, metrics) {
    let s = 30;
    const rank = metrics.volRank ?? 0.5;
    if (rank <= 0.10) s += 25; else if (rank <= 0.25) s += 18; else if (rank <= 0.5) s += 10;
    const sp = metrics.spread ?? 0.1;
    if (sp <= 0.03) s += 20; else if (sp <= 0.07) s += 12; else if (sp <= 0.12) s += 6;
    const mv = metrics.moveAbs ?? 0;
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

  /* Implied ROI if the YES side resolves at $1.00 — pure arithmetic on the price. */
  impliedRoi(price) { return price && price > 0 ? (1 - price) / price : null; },

  MODEL_FEED_THRESHOLD: 65,
};

/* Ring-buffered alert engine with per-market cooldown. */
class AlertEngine {
  constructor(cooldownMs = 90000) {
    this.state = new Map();
    this.cooldownMs = cooldownMs;
    this.windowMs = 120000;   // intra-window detection (default 2 minutes)
    this.historyMs = 10 * 60 * 1000; // keep 10 min of points
  }

  update(key, price, meta) {
    if (price == null || !Number.isFinite(price)) return null;
    const now = Date.now();
    let s = this.state.get(key);
    if (!s) {
      s = { ref: price, history: [[now, price]], lastAlertAt: 0 };
      this.state.set(key, s);
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
    if (Math.abs(deltaSession) >= 0.10) { move = 'session'; delta = deltaSession; }
    else if (Math.abs(deltaWindow) >= 0.10) { move = 'window'; delta = deltaWindow; }

    if (move && now - s.lastAlertAt >= this.cooldownMs) {
      s.lastAlertAt = now;
      return {
        id: key + '_' + now,
        key, ticker: meta.ticker, title: meta.title, topic: meta.topic,
        price, delta, move, deltaSession, deltaWindow,
        direction: delta >= 0 ? 'up' : 'down',
        ts: now,
      };
    }
    return null;
  }

  snapshot(key) { return this.state.get(key) || null; }
}
