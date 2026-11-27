/* strategies.js — Strategy Lab.
   Backtests are MONTE CARLO simulations over synthetic price paths (seeded & reproducible),
   plus an optional live scanner against the demo API. No real orders are placed here.
   Fee model: Kalshi taker fee  roundup(0.07 × C × P × (1−P))  on entry and exit;
   positions held to resolution pay no exit fee (settlement is free). */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);

  const CONTRACTS = 10;
  const START_BANKROLL = 10000;
  const PATHS_PER_MARKET = 20;
  const PATH_STEPS = 240;
  const MAX_CONCURRENT = 5;

  const STRATEGIES = [
    { id: 'momentum', name: 'Momentum Breakout', type: 'Momentum', desc: 'Buy YES when the 20-step change is ≥ +$0.08 and rising. Take profit +$0.15, stop loss −$0.10, else hold to resolution.' },
    { id: 'meanrev', name: 'Mean Reversion (Fade the Drop)', type: 'Mean reversion', desc: 'Buy YES after a 20-step drop of ≥ $0.08. Take profit +$0.12, stop loss −$0.10, else hold to resolution.' },
    { id: 'model', name: 'Model High-ROI', type: 'Model / High-ROI', desc: 'Buy YES when the contract sits in the model zone (price $0.50–$0.85, 20-step change ≥ +$0.05, tight synthetic spread). Take profit +$0.15, stop −$0.10.' },
    { id: 'favorite', name: 'Tail-End Favorite', type: 'Tail favorite', desc: 'Buy YES when price ≥ $0.85 and hold to resolution. Small edge, high hit-rate profile.' },
    { id: 'scalp', name: 'Micro Scalp', type: 'Scalp', desc: 'Buy YES after a $0.06 move in 5 steps. Exit at +$0.04 or −$0.05; max 30 steps per trade.' },
  ];

  /* Delegates to the tested implementation so the lab cannot drift from the published
     fee table (see terminal/tests/core.test.mjs). */
  function fee(qty, price) { return PaperFees.taker(qty, price); }

  /* Outcome of a synthetic path: P(YES) drawn once from the starting price (calibration). */
  function pathOutcome(rand, startPrice) { return rand() < startPrice ? 1 : 0; }

  function backtestStrategy(stratId, paths) {
    const trades = [];
    let cash = START_BANKROLL;
    const equityCurve = [cash];
    let openCount = 0;
    let peak = cash, maxDD = 0;

    for (const path of paths) {
      const pts = path.points;
      const outcome = path.outcome;
      let inTrade = null; // {entryIdx, entryPrice, entryFee}
      for (let i = 20; i < pts.length; i++) {
        const p = pts[i];
        if (inTrade) {
          const change = p - inTrade.entryPrice;
          let exitReason = null, exitPrice = null, exitFee = 0;
          if (stratId === 'scalp' && i - inTrade.entryIdx >= 30) { exitReason = 'time'; exitPrice = p; }
          if (change >= (stratId === 'scalp' ? 0.04 : stratId === 'meanrev' ? 0.12 : 0.15)) { exitReason = 'take_profit'; exitPrice = p; }
          else if (change <= (stratId === 'scalp' ? -0.05 : -0.10)) { exitReason = 'stop_loss'; exitPrice = p; }
          else if (i === pts.length - 1) { exitReason = 'resolution'; exitPrice = outcome; }
          if (exitReason) {
            exitFee = exitReason === 'resolution' ? 0 : fee(CONTRACTS, exitPrice);
            const pnl = (exitPrice - inTrade.entryPrice) * CONTRACTS - inTrade.entryFee - exitFee;
            cash += pnl + CONTRACTS * inTrade.entryPrice + inTrade.entryFee; // release stake (stake was deducted at entry)
            trades.push({ strategy: stratId, topic: path.topic, ticker: path.ticker, entry: inTrade.entryPrice, exit: exitPrice, pnl, roi: pnl / (inTrade.entryPrice * CONTRACTS + inTrade.entryFee), reason: exitReason, contractType: exitReason === 'resolution' ? (outcome ? 'YES won' : 'YES lost') : 'closed early', atStep: i });
            inTrade = null;
            openCount--;
          }
          equityCurve.push(cash);
          peak = Math.max(peak, cash); maxDD = Math.max(maxDD, peak - cash);
          continue;
        }
        if (openCount >= MAX_CONCURRENT) continue;
        let signal = false;
        const chg20 = pts[i] - pts[i - 20];
        const chg5 = pts[i] - pts[i - 5];
        if (stratId === 'momentum') signal = chg20 >= 0.08 && pts[i] >= pts[i - 1];
        else if (stratId === 'meanrev') signal = chg20 <= -0.08;
        else if (stratId === 'model') signal = p >= 0.50 && p <= 0.85 && chg20 >= 0.05;
        else if (stratId === 'favorite') signal = p >= 0.85;
        else if (stratId === 'scalp') signal = Math.abs(chg5) >= 0.06;
        if (signal) {
          const entryFee = fee(CONTRACTS, p);
          const stake = CONTRACTS * p + entryFee;
          if (stake > cash) continue;
          cash -= stake;
          inTrade = { entryIdx: i, entryPrice: p, entryFee };
          openCount++;
        }
      }
      if (inTrade) { /* closed at resolution inside loop at i === last */ }
    }

    const wins = trades.filter(t => t.pnl > 0).length;
    const totalPnl = trades.reduce((s, t) => s + t.pnl, 0);
    const grossWin = trades.filter(t => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
    const grossLoss = Math.abs(trades.filter(t => t.pnl <= 0).reduce((s, t) => s + t.pnl, 0));
    const avgRoi = trades.length ? trades.reduce((s, t) => s + t.roi, 0) / trades.length : 0;
    return {
      stratId, trades: trades.length, wins,
      winRate: trades.length ? wins / trades.length : 0,
      totalPnl, avgRoi,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : 0),
      maxDrawdown: maxDD,
      tradesList: trades,
    };
  }

  function buildPaths(seed) {
    const paths = [];
    for (const t of TOPICS) {
      const topicMarkets = SimulatedFeed.SIM_MARKETS.filter(m => m.topic === t.id);
      for (const m of topicMarkets) {
        for (let k = 0; k < PATHS_PER_MARKET; k++) {
          const pathSeed = (seed ^ (t.id.length * 131) ^ (k * 2654435761) ^ m.ticker.length * 97) >>> 0;
          const rand = SimulatedFeed.rng(pathSeed);
          paths.push({ topic: t.id, ticker: m.ticker, points: SimulatedFeed.makePath(pathSeed, m.p, PATH_STEPS), outcome: pathOutcome(rand, m.p) });
        }
      }
    }
    return paths;
  }

  function fmtMoney(n) { return (n < 0 ? '-$' : '+$') + Math.abs(n).toFixed(2); }

  function drawEquity(canvas, curves) {
    const ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr; canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = rect.width, H = rect.height, padL = 56, padR = 10, padT = 12, padB = 24;
    ctx.clearRect(0, 0, W, H);
    const all = curves.flatMap(c => c.points);
    const min = Math.min(...all, START_BANKROLL), max = Math.max(...all, START_BANKROLL);
    const span = Math.max(1, max - min);
    const X = (i, n) => padL + (i / (n - 1)) * (W - padL - padR);
    const Y = (v) => padT + (1 - (v - min) / span) * (H - padT - padB);
    // zero-line (bankroll)
    ctx.strokeStyle = '#243154'; ctx.beginPath(); ctx.moveTo(padL, Y(START_BANKROLL)); ctx.lineTo(W - padR, Y(START_BANKROLL)); ctx.stroke();
    ctx.fillStyle = '#8b96b8'; ctx.font = '11px ui-monospace, Menlo, monospace';
    ctx.fillText('$' + START_BANKROLL.toFixed(0), 6, Y(START_BANKROLL));
    for (const c of curves) {
      ctx.beginPath();
      c.points.forEach((v, i) => { const x = X(i, c.points.length), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.strokeStyle = c.color; ctx.lineWidth = 1.6; ctx.stroke();
    }
    ctx.fillStyle = '#8b96b8';
    ctx.fillText('trade index →', W - 92, H - 14);
  }

  function run(seed) {
    $('#seedLabel').textContent = String(seed);
    const paths = buildPaths(seed);
    const results = STRATEGIES.map(s => backtestStrategy(s.id, paths));
    const allTrades = results.flatMap(r => r.tradesList.map(t => ({ ...t, strategyName: STRATEGIES.find(s => s.id === r.stratId).name, strategyType: STRATEGIES.find(s => s.id === r.stratId).type })));

    // --- per-strategy table ---
    $('#strategyTable tbody').innerHTML = results.map(r => {
      const s = STRATEGIES.find(x => x.id === r.stratId);
      return `<tr>
        <td><strong>${escapeHtml(s.name)}</strong><div class="muted small">${escapeHtml(s.desc)}</div></td>
        <td class="num">${r.trades}</td>
        <td class="num ${r.winRate >= 0.5 ? 'up' : 'down'}">${(r.winRate * 100).toFixed(1)}%</td>
        <td class="num ${r.totalPnl >= 0 ? 'up' : 'down'}">${fmtMoney(r.totalPnl)}</td>
        <td class="num">${(r.avgRoi * 100).toFixed(1)}%</td>
        <td class="num">${r.profitFactor === Infinity ? '∞' : r.profitFactor.toFixed(2)}</td>
        <td class="num">-$${r.maxDrawdown.toFixed(2)}</td>
      </tr>`;
    }).join('');

    // --- topic × strategy P&L matrix ---
    const matrix = {};
    for (const t of TOPICS) { matrix[t.id] = {}; for (const s of STRATEGIES) matrix[t.id][s.id] = 0; }
    for (const t of allTrades) matrix[t.topic][t.strategy] += t.pnl;
    $('#topicMatrix thead').innerHTML = '<tr><th>Topic</th>' + STRATEGIES.map(s => `<th class="num">${escapeHtml(s.name.split(' ')[0])}</th>`).join('') + '<th class="num">Total</th></tr>';
    $('#topicMatrix tbody').innerHTML = TOPICS.map(t => {
      const cells = STRATEGIES.map(s => `<td class="num ${matrix[t.id][s.id] >= 0 ? 'up' : 'down'}">${fmtMoney(matrix[t.id][s.id])}</td>`).join('');
      const total = STRATEGIES.reduce((sum, s) => sum + matrix[t.id][s.id], 0);
      return `<tr><td><span class="badge topic-${t.id}">${escapeHtml(t.short)}</span></td>${cells}<td class="num ${total >= 0 ? 'up' : 'down'}"><strong>${fmtMoney(total)}</strong></td></tr>`;
    }).join('');

    // --- by trade type ---
    const byType = {};
    for (const t of allTrades) { (byType[t.strategyType] = byType[t.strategyType] || { n: 0, wins: 0, pnl: 0 }); byType[t.strategyType].n++; if (t.pnl > 0) byType[t.strategyType].wins++; byType[t.strategyType].pnl += t.pnl; }
    $('#typeTable tbody').innerHTML = Object.entries(byType).map(([type, d]) => `<tr><td>${escapeHtml(type)}</td><td class="num">${d.n}</td><td class="num">${(100 * d.wins / d.n).toFixed(1)}%</td><td class="num ${d.pnl >= 0 ? 'up' : 'down'}">${fmtMoney(d.pnl)}</td></tr>`).join('');

    // --- auto-generated insights ---
    const best = [...results].sort((a, b) => b.totalPnl - a.totalPnl)[0];
    const worst = [...results].sort((a, b) => a.totalPnl - b.totalPnl)[0];
    const topicTotals = TOPICS.map(t => ({ t, pnl: STRATEGIES.reduce((s, st) => s + matrix[t.id][st.id], 0) })).sort((a, b) => b.pnl - a.pnl);
    $('#autoInsights').innerHTML = `
      <li>Best simulated strategy this run: <strong>${escapeHtml(STRATEGIES.find(s => s.id === best.stratId).name)}</strong> (${fmtMoney(best.totalPnl)} over ${best.trades} trades).</li>
      <li>Weakest this run: <strong>${escapeHtml(STRATEGIES.find(s => s.id === worst.stratId).name)}</strong> (${fmtMoney(worst.totalPnl)}). Synthetic paths carry no alpha — treat this as a harness check, not an edge.</li>
      <li>Top topic by simulated P&amp;L: <strong>${escapeHtml(topicTotals[0].t.name)}</strong> (${fmtMoney(topicTotals[0].pnl)}).</li>
      <li>Fees matter: at 10 contracts per trade the taker fee is <code>ceil(0.07×C×P×(1−P))</code> — highest near P=$0.50.</li>
      <li>Every result above is a Monte Carlo simulation on synthetic paths, not a backtest on real Kalshi history and not financial advice.</li>`;

    // --- equity curves ---
    const colors = { momentum: '#5aa9ff', meanrev: '#ffc44d', model: '#00dd94', favorite: '#c084fc', scalp: '#ff6b6b' };
    const curves = results.map(r => {
      // rebuild equity progression for drawing (approx from trades order)
      let eq = START_BANKROLL; const pts = [eq];
      for (const t of r.tradesList) { eq += t.pnl; pts.push(eq); }
      return { label: r.stratId, color: colors[r.stratId], points: pts };
    });
    drawEquity($('#equityChart'), curves);
    $('#equityLegend').innerHTML = STRATEGIES.map(s => `<span class="badge" style="border-color:${colors[s.id]};color:${colors[s.id]}">■ ${escapeHtml(s.name)}</span>`).join(' ');

    // stash trades for CSV export
    state.lastTrades = allTrades;
    $('#simSummary').textContent = `Simulated ${allTrades.length} trades across ${paths.length} synthetic paths × ${STRATEGIES.length} strategies · contracts/trade=${CONTRACTS} · seed=${seed}.`;
  }

  const state = { lastTrades: [] };

  /* ---------- live scanner (best-effort) ---------- */
  async function liveScan() {
    const el = $('#liveScanBody');
    try {
      const res = await Kalshi.getEvents({ status: 'open', limit: 100 });
      if (!res.ok) throw new Error('HTTP ' + (res.status || 'network/CORS'));
      const flat = await Kalshi.flattenEvents(res);
      const rows = flat.map(({ event, market }) => {
        const row = Desk.buildRow(event, market);
        if (!row) return null;
        return { topic: row.topic, title: row.title, ticker: row.ticker, last: row.price, spread: row.spread, vol: row.volume, oi: row.openInterest, evidence: row.topicEvidence };
      }).filter(Boolean);
      rows.sort((a, b) => b.vol - a.vol);
      const top = rows.slice(0, 8);
      el.innerHTML = top.length ? top.map(r => `
        <tr>
          <td><span class="badge topic-${r.topic}">${escapeHtml((TOPIC_BY_ID[r.topic] || {}).short)}</span></td>
          <td style="max-width:380px" title="${escapeHtml(r.title)}">${escapeHtml(truncate(r.title, 95))}</td>
          <td class="mono small">${escapeHtml(r.ticker)}</td>
          <td class="num">${fmtCents(r.last)}</td>
          <td class="num">${fmtCents(r.spread)}</td>
          <td class="num">${fmtContracts(r.vol)}</td>
          <td class="num">${r.last > 0 ? '+' + ((1 - r.last) / r.last * 100).toFixed(0) + '%' : '—'}</td>
        </tr>`).join('') : '<tr class="empty-row"><td colspan="7">Connected, but no tracked-topic contracts matched.</td></tr>';
      $('#liveScanNote').textContent = 'Live snapshot from the demo API (public endpoints), sorted by volume. Prices move — re-open this page or use the dashboard for streaming values.';
    } catch (err) {
      el.innerHTML = '<tr class="empty-row"><td colspan="7">Live scanner unavailable (' + escapeHtml(String(err.message || err)) + '). The simulation above still works offline.</td></tr>';
      $('#liveScanNote').textContent = 'The demo API was unreachable from this browser (network/CORS). This panel needs connectivity; everything else on this page is self-contained.';
    }
  }

  function truncate(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  document.addEventListener('DOMContentLoaded', () => {
    let seed = 20261122;
    $('#rerunBtn').addEventListener('click', () => { seed = (Math.random() * 0xffffffff) >>> 0; run(seed); });
    $('#exportTradesBtn').addEventListener('click', () => {
      if (!state.lastTrades.length) { toast('Nothing to export yet'); return; }
      const header = 'strategy,type,topic,ticker,entry,exit,pnl,roi,reason\n';
      const body = state.lastTrades.map(t => [t.strategyName, t.strategyType, t.topic, t.ticker, t.entry.toFixed(4), t.exit.toFixed(4), t.pnl.toFixed(4), t.roi.toFixed(4), t.reason].join(',')).join('\n');
      const url = URL.createObjectURL(new Blob([header + body], { type: 'text/csv' }));
      const a = document.createElement('a'); a.href = url; a.download = 'tradebot1-simulated-trades.csv'; a.click(); URL.revokeObjectURL(url);
    });
    run(seed);
    liveScan();
  });
})();
