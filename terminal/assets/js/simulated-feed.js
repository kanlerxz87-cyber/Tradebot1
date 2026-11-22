/* simulated-feed.js — SYNTHETIC, clearly-labeled fallback data.
   Used only when the demo API cannot be reached from the browser
   (network/CORS/timeout) or for offline strategy backtests.
   Every value produced here is fictional and must be labeled SIMULATED in the UI. */
'use strict';

const SimulatedFeed = (() => {
  /* mulberry32 — deterministic PRNG so backtests are reproducible */
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const SIM_MARKETS = [
    // Gas
    { ticker: 'SIM-GAS-001', title: 'SIM: Will US retail gasoline average above $3.75/gal in December 2026?', topic: 'gas', p: 0.42, vol: 182000 },
    { ticker: 'SIM-GAS-002', title: 'SIM: Will WTI crude settle above $80 on Dec 31, 2026?', topic: 'gas', p: 0.38, vol: 149500 },
    { ticker: 'SIM-GAS-003', title: 'SIM: Will US natural gas Henry Hub exceed $4.50 this winter season?', topic: 'gas', p: 0.31, vol: 98000 },
    // Elections
    { ticker: 'SIM-ELEC-001', title: 'SIM: Will Democrats win the US Senate in 2026 midterms?', topic: 'elections', p: 0.55, vol: 240000 },
    { ticker: 'SIM-ELEC-002', title: 'SIM: Will Republicans hold the House in 2026 midterms?', topic: 'elections', p: 0.58, vol: 213000 },
    { ticker: 'SIM-ELEC-003', title: 'SIM: Will the incumbent win the next Georgia gubernatorial race?', topic: 'elections', p: 0.47, vol: 87000 },
    // Culture
    { ticker: 'SIM-CULT-001', title: 'SIM: Will the Best Picture Oscar go to a fictional release led by a streaming platform?', topic: 'culture', p: 0.36, vol: 121000 },
    { ticker: 'SIM-CULT-002', title: 'SIM: Will the top global tour of 2026 sell over 5M tickets?', topic: 'culture', p: 0.44, vol: 76000 },
    { ticker: 'SIM-CULT-003', title: 'SIM: Will a major album break 1B streams in a week this December?', topic: 'culture', p: 0.61, vol: 69000 },
    // Crypto
    { ticker: 'SIM-CRYPTO-001', title: 'SIM: Will Bitcoin close above $120,000 on Dec 31, 2026?', topic: 'crypto', p: 0.35, vol: 310000 },
    { ticker: 'SIM-CRYPTO-002', title: 'SIM: Will Ethereum close above $5,000 on Dec 31, 2026?', topic: 'crypto', p: 0.33, vol: 205000 },
    { ticker: 'SIM-CRYPTO-003', title: 'SIM: Will a spot Solana ETF be approved in the US by March 2027?', topic: 'crypto', p: 0.52, vol: 134000 },
    // Golf
    { ticker: 'SIM-GOLF-001', title: 'SIM: Will a first-time winner take the 2026 PGA Championship?', topic: 'golf', p: 0.40, vol: 88000 },
    { ticker: 'SIM-GOLF-002', title: 'SIM: Will the 2027 Masters leader after Round 1 be a first-time leader?', topic: 'golf', p: 0.57, vol: 54000 },
    { ticker: 'SIM-GOLF-003', title: 'SIM: Will LIV Golf retain 4+ major winners for 2027 season?', topic: 'golf', p: 0.29, vol: 41000 },
  ];

  /* Build a live-ish market object matching the shape the dashboard expects. */
  function makeMarket(seed, idx) {
    const r = rng(seed + idx * 7919);
    const base = SIM_MARKETS[idx % SIM_MARKETS.length];
    const p = Math.min(0.92, Math.max(0.08, base.p + (r() - 0.5) * 0.06));
    return {
      ticker: base.ticker,
      event_ticker: base.ticker.replace(/-\d+$/, ''),
      series_ticker: 'SIM',
      title: base.title,
      subtitle: 'Synthetic demonstration market — not a real Kalshi contract.',
      category: 'Simulation',
      status: 'open',
      yes_bid_dollars: (p - 0.01).toFixed(4),
      yes_ask_dollars: (p + 0.01).toFixed(4),
      no_bid_dollars: (1 - p - 0.01).toFixed(4),
      no_ask_dollars: (1 - p + 0.01).toFixed(4),
      last_price_dollars: p.toFixed(4),
      previous_price_dollars: base.p.toFixed(4),
      volume_fp: String(base.vol),
      volume_24h_fp: String(Math.round(base.vol * 0.12)),
      open_interest_fp: String(Math.round(base.vol * 0.35)),
      close_time: new Date(Date.now() + 14 * 86400000).toISOString(),
      result: '',
      _sim: true,
      _topic: base.topic,
    };
  }

  function makeSnapshot(seed) {
    const markets = SIM_MARKETS.map((_, i) => makeMarket(seed, i));
    return markets.map(m => ({ event: {
      event_ticker: m.event_ticker, title: m.title.replace(/^SIM: /, ''), series_ticker: 'SIM',
      category: 'Simulation', status: 'open', mutually_exclusive: false,
    }, market: m }));
  }

  /* Random-walk step for a simulated market. Occasionally jumps ≥ $0.10 to
     exercise the alert path. Returns new price (clamped to [0.03, 0.97]). */
  function stepPrice(price, rand) {
    const jump = rand() < 0.035 ? (rand() < 0.5 ? -1 : 1) * (0.10 + rand() * 0.08) : 0;
    const drift = (rand() - 0.5) * 0.012;
    return Math.min(0.97, Math.max(0.03, price + drift + jump));
  }

  /* Synthetic intraday path for backtests. n steps of ~1 minute. */
  function makePath(seed, startPrice, n) {
    const rand = rng(seed);
    const points = new Array(n);
    let p = startPrice;
    for (let i = 0; i < n; i++) {
      p = stepPrice(p, rand);
      points[i] = p;
    }
    return points;
  }

  const syntheticOrderbook = (midPrice, seed) => {
    const rand = rng(seed);
    const yes = [], no = [];
    for (let i = 1; i <= 8; i++) {
      const bid = Math.max(0.01, midPrice - i * 0.01);
      const ask = Math.min(0.99, midPrice + i * 0.01);
      yes.push([bid, Math.round(rand() * 900 + 120)]);
      no.push([Math.round((1 - ask) * 100) / 100, Math.round(rand() * 900 + 120)]);
    }
    return { yes, no };
  };

  return { SIM_MARKETS, rng, makeSnapshot, makeMarket, makePath, stepPrice, syntheticOrderbook };
})();
