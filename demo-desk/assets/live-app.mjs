import {
  ALLOWED_TOPICS,
  BUILTIN_STRATEGIES,
  rawTakerFee6dp,
  applyFeeAccumulator,
  normalizeOrderbook,
  estimateOrderbookFill,
  evaluateSwing,
  generateStrategySignals,
  settlementPayoutPerContract
} from "./live-core.mjs";

const STORAGE_KEY = "kalshi_live_demo_desk_v2";
const DEMO_REST_BASES = [
  "https://external-api.demo.kalshi.co/trade-api/v2",
  "https://demo-api.kalshi.co/trade-api/v2"
];
const DEMO_REST = DEMO_REST_BASES[0];

function esc(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtUsd(n, dp = 2) {
  const num = Number(n || 0);
  const sign = num < 0 ? "-" : "";
  return `${sign}$${Math.abs(num).toFixed(dp)}`;
}

function fmtNum(n, dp = 2) {
  return Number(n || 0).toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp
  });
}

function resolveApiPath(relApiPath) {
  // Works whether served at /demo-desk/ or /Tradebot1/demo-desk/ or subpage /demo-desk/portfolio/
  const path = window.location.pathname || "/";
  const idx = path.indexOf("/demo-desk/");
  const rootPrefix = idx >= 0 ? path.slice(0, idx) : "";
  return `${rootPrefix}${relApiPath}`;
}

async function fetchDemoPublicJson(endpointPath) {
  const clean = endpointPath.startsWith("/") ? endpointPath : `/${endpointPath}`;
  let lastErr = null;
  for (const base of DEMO_REST_BASES) {
    try {
      const res = await fetch(`${base}${clean}`, { mode: "cors", cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return { data, via: base };
    } catch (err) {
      lastErr = err;
    }
  }
  // Fallback to same-origin read-only relay (/api/demo/public) when running kalshi_engine.relay_server
  try {
    const relayRes = await fetch(
      `${resolveApiPath("/api/demo/public")}?endpoint=${encodeURIComponent(clean)}`,
      { cache: "no-store" }
    );
    if (relayRes.ok) {
      const payload = await relayRes.json();
      if (payload?.ok && payload?.data) {
        return { data: payload.data, via: "/api/demo/public" };
      }
    }
  } catch {
    // Static GitHub Pages has no server endpoint; ignore fallback error
  }
  throw lastErr || new Error("Unreachable");
}

function defaultState() {
  return {
    startingBankroll: 10000,
    cash: 10000,
    feeAccumulator: 0,
    totalFeesCharged: 0,
    enabledStrategies: [
      "momentum_breakout",
      "mean_reversion_fade",
      "high_roi_selective",
      "favorite_compounder",
      "longshot_asymmetric"
    ],
    customStrategies: [
      {
        id: "custom_crypto_fade",
        name: "Custom Crypto Oversold Buyer",
        trade_type: "custom_rule",
        topic: "Crypto",
        direction: "down",
        side: "yes",
        min_abs_delta: 0.10,
        min_price: 0.25,
        max_price: 0.48,
        contracts: 15,
        enabled: true
      }
    ],
    trades: [],
    seeded: false,
    routeLiveRelayOrders: false
  };
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw);
    return { ...defaultState(), ...parsed };
  } catch {
    return defaultState();
  }
}

function saveState(st) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(st));
  } catch {
    // Private browsing fallback
  }
}

function recordTrade(st, trade) {
  const contracts = Number(trade.contracts);
  const price = Number(trade.price);
  const feeMult = trade.fee_multiplier !== undefined ? Number(trade.fee_multiplier) : 1;
  const cost = Number((contracts * price).toFixed(4));
  const raw6dp = rawTakerFee6dp(contracts, price, 0.07, feeMult);
  const feeRes = applyFeeAccumulator(raw6dp, st.feeAccumulator, true, -cost);
  if (st.cash < cost + feeRes.charged) return null;

  st.cash = Number((st.cash - cost - feeRes.charged).toFixed(4));
  st.feeAccumulator = feeRes.nextAccumulator;
  st.totalFeesCharged = Number((st.totalFeesCharged + feeRes.charged).toFixed(6));

  const entry = {
    id: `tr-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    ts: trade.ts || new Date().toISOString(),
    ticker: trade.ticker,
    topic: trade.topic,
    strategy_id: trade.strategy_id,
    strategy_label: trade.strategy_label,
    trade_type: trade.trade_type,
    side: trade.side,
    contracts,
    price,
    fee_multiplier: feeMult,
    cost,
    fee_raw_6dp: raw6dp,
    fee_charged: feeRes.charged,
    settled: Boolean(trade.settled),
    settlement_result: trade.settlement_result || "",
    payout: Number(trade.payout || 0),
    realized_pnl: Number(trade.realized_pnl || 0),
    mode: trade.mode || "simulated_demo",
    source_url: trade.source_url || `${DEMO_REST}/markets/${trade.ticker}`
  };
  st.trades.unshift(entry);
  return entry;
}

function settleTradesForMarket(st, ticker, result, settlementValueDollars = null) {
  let count = 0;
  for (const tr of st.trades) {
    if (tr.ticker !== ticker || tr.settled) continue;
    const unitPayout = settlementPayoutPerContract(tr.side, result, settlementValueDollars);
    const payout = Number((tr.contracts * unitPayout).toFixed(4));
    tr.settled = true;
    tr.settlement_result = String(result).toLowerCase();
    tr.payout = payout;
    tr.realized_pnl = Number((payout - tr.cost - tr.fee_charged).toFixed(4));
    st.cash = Number((st.cash + payout).toFixed(4));
    count += 1;
  }
  return count;
}

function seedInitialPortfolioIfNeeded(st, snap) {
  if (st.seeded) return;
  for (const sw of [...snap.swings].reverse()) {
    const sigs = generateStrategySignals(sw, st.enabledStrategies, st.customStrategies);
    for (const sig of sigs) {
      recordTrade(st, {
        ...sig,
        ts: sw.ts,
        ticker: sw.ticker,
        topic: sw.topic,
        source_url: sw.api_url
      });
    }
  }
  // Seed two verified 2026-11-27 finalized settlements (YES on Gas $3.60 & NO fade on BTC H19)
  const gasTr = recordTrade(st, {
    ts: "2026-11-27T18:30:00Z",
    ticker: "KXAAAGASMIN-26DEC31-3.60",
    topic: "Gas Prices",
    strategy_id: "favorite_compounder",
    strategy_label: "Favorite Compounder",
    trade_type: "tail_convexity",
    side: "yes",
    contracts: 15,
    price: 0.90,
    source_url: `${DEMO_REST}/events/KXAAAGASMIN-26DEC31?with_nested_markets=true`
  });
  if (gasTr) settleTradesForMarket(st, "KXAAAGASMIN-26DEC31-3.60", "yes", "1.0000");

  const btcH19Tr = recordTrade(st, {
    ts: "2026-11-27T18:55:00Z",
    ticker: "KXDEMOFUTHOURLY-26NOV27H19-UP",
    topic: "Crypto",
    strategy_id: "mean_reversion_fade",
    strategy_label: "Mean-Reversion Fade",
    trade_type: "mean_reversion",
    side: "no",
    contracts: 20,
    price: 0.35,
    source_url: `${DEMO_REST}/markets/KXDEMOFUTHOURLY-26NOV27H19-UP`
  });
  if (btcH19Tr) settleTradesForMarket(st, "KXDEMOFUTHOURLY-26NOV27H19-UP", "no", "0.0000");

  st.seeded = true;
  saveState(st);
}

function computePortfolioMetrics(st, snap) {
  const mMap = new Map(snap.markets.map((m) => [m.ticker, m]));
  let openMarkValue = 0;
  let openCost = 0;
  let realizedPnl = 0;

  const byStrategy = new Map();
  const byType = new Map();

  for (const t of st.trades) {
    let markPrice = t.price;
    const m = mMap.get(t.ticker);
    if (m) {
      const yesLast = Number(m.last_price_dollars || m.yes_bid_dollars || t.price);
      markPrice = t.side === "yes" ? yesLast : Number((1 - yesLast).toFixed(4));
    }
    const currentVal = t.settled ? t.payout : Number((t.contracts * markPrice).toFixed(4));
    const pnl = t.settled ? t.realized_pnl : Number((currentVal - t.cost - t.fee_charged).toFixed(4));

    if (!t.settled) {
      openMarkValue += currentVal;
      openCost += t.cost;
    } else {
      realizedPnl += t.realized_pnl;
    }

    for (const [map, key, label] of [
      [byStrategy, t.strategy_id, t.strategy_label],
      [byType, t.trade_type, t.trade_type]
    ]) {
      if (!map.has(key)) {
        map.set(key, {
          key,
          label,
          trades: 0,
          contracts: 0,
          notional: 0,
          fees: 0,
          pnl: 0,
          wins: 0
        });
      }
      const agg = map.get(key);
      agg.trades += 1;
      agg.contracts += t.contracts;
      agg.notional += t.cost;
      agg.fees += t.fee_charged;
      agg.pnl += pnl;
      if (pnl > 0) agg.wins += 1;
    }
  }

  const equity = Number((st.cash + openMarkValue).toFixed(2));
  const netPnl = Number((equity - st.startingBankroll).toFixed(2));
  return {
    equity,
    netPnl,
    openMarkValue: Number(openMarkValue.toFixed(2)),
    openCost: Number(openCost.toFixed(2)),
    realizedPnl: Number(realizedPnl.toFixed(2)),
    byStrategy: [...byStrategy.values()].sort((a, b) => b.pnl - a.pnl),
    byType: [...byType.values()].sort((a, b) => b.pnl - a.pnl)
  };
}

function buildChartSeries(snap, market, windowMode) {
  const hist = snap.series_history?.[market.ticker];
  if (hist?.[windowMode]?.length) return hist[windowMode];
  if (hist?.hours?.length) return hist.hours;
  const prev = Number(market.previous_price_dollars || market.last_price_dollars || 0);
  const curr = Number(market.last_price_dollars || 0);
  return [
    {
      ts: "2026-11-26T19:49:18Z",
      price: prev,
      source_url: market.api_url,
      catalyst_url: market.settlement_source_url
    },
    {
      ts: snap.captured_at,
      price: curr,
      source_url: market.api_url,
      catalyst_url: market.settlement_source_url
    }
  ];
}

function drawPriceChart(canvas, tooltipEl, points, market) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, rect.width || 680);
  const height = Math.max(240, rect.height || 290);
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const pad = { top: 20, right: 22, bottom: 36, left: 52 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0b111e";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#1e293b";
  ctx.lineWidth = 1;
  ctx.font = "11px ui-monospace, monospace";
  ctx.fillStyle = "#93a4c3";
  for (let i = 0; i <= 4; i++) {
    const val = i * 0.25;
    const y = pad.top + plotH * (1 - val);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillText(`$${val.toFixed(2)}`, 8, y + 4);
  }

  if (!points.length) return;

  const coords = points.map((pt, idx) => {
    const x = pad.left + (points.length === 1 ? plotW / 2 : (idx / (points.length - 1)) * plotW);
    const y = pad.top + plotH * (1 - Math.min(1, Math.max(0, Number(pt.price))));
    const prevPrice = idx > 0 ? Number(points[idx - 1].price) : Number(pt.price);
    const delta = Number((Number(pt.price) - prevPrice).toFixed(4));
    return { ...pt, x, y, delta, isJump: idx > 0 && Math.abs(delta) + 1e-9 >= 0.10 };
  });

  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  grad.addColorStop(0, "rgba(56, 189, 248, 0.28)");
  grad.addColorStop(1, "rgba(56, 189, 248, 0.01)");
  ctx.beginPath();
  coords.forEach((c, idx) => (idx === 0 ? ctx.moveTo(c.x, c.y) : ctx.lineTo(c.x, c.y)));
  ctx.lineTo(coords[coords.length - 1].x, pad.top + plotH);
  ctx.lineTo(coords[0].x, pad.top + plotH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  coords.forEach((c, idx) => (idx === 0 ? ctx.moveTo(c.x, c.y) : ctx.lineTo(c.x, c.y)));
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 2.2;
  ctx.stroke();

  coords.forEach((c) => {
    if (c.isJump) {
      ctx.save();
      ctx.translate(c.x, c.y);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = c.delta > 0 ? "#22c55e" : "#f43f5e";
      ctx.fillRect(-5, -5, 10, 10);
      ctx.restore();
    } else {
      ctx.beginPath();
      ctx.arc(c.x, c.y, 3.2, 0, Math.PI * 2);
      ctx.fillStyle = "#bae6fd";
      ctx.fill();
    }
  });

  ctx.fillStyle = "#93a4c3";
  const labelIndices = [0, Math.floor((coords.length - 1) / 2), coords.length - 1];
  [...new Set(labelIndices)].forEach((idx) => {
    const c = coords[idx];
    if (!c) return;
    const label = String(c.ts).replace("2026-11-", "Nov ").replace(".000Z", "Z");
    const tw = ctx.measureText(label).width;
    const tx = Math.min(width - pad.right - tw, Math.max(pad.left, c.x - tw / 2));
    ctx.fillText(label, tx, height - 10);
  });

  const showPoint = (c) => {
    if (!tooltipEl || !c) return;
    const jumpBadge = c.isJump
      ? `<span class="badge ${c.delta > 0 ? "ok" : "down"}">Jump ${c.delta > 0 ? "+" : ""}$${c.delta.toFixed(2)} (&ge;$0.10)</span>`
      : `<span class="badge">Δ ${c.delta >= 0 ? "+" : ""}$${c.delta.toFixed(3)}</span>`;
    tooltipEl.innerHTML = `
      <div>
        <strong class="mono">${esc(market.ticker)}</strong> · <span class="mono">${esc(c.ts)}</span> ·
        Price: <strong class="mono">$${Number(c.price).toFixed(4)}</strong> ${jumpBadge}
      </div>
      <div>
        <a href="${esc(c.source_url || market.api_url)}" target="_blank" rel="noopener">Kalshi API Source ↗</a> ·
        <a href="${esc(c.catalyst_url || market.settlement_source_url)}" target="_blank" rel="noopener">Catalyst / Settlement Source (${esc(market.settlement_source_name)}) ↗</a>
      </div>
    `;
  };

  const latestJump = [...coords].reverse().find((c) => c.isJump) || coords[coords.length - 1];
  showPoint(latestJump);

  canvas.onmousemove = (ev) => {
    const r = canvas.getBoundingClientRect();
    const mx = ev.clientX - r.left;
    let best = coords[0];
    let bestDist = Infinity;
    for (const c of coords) {
      const d = Math.abs(c.x - mx);
      if (d < bestDist) {
        bestDist = d;
        best = c;
      }
    }
    showPoint(best);
  };
}

function renderOrderbookPanel(container, snap, market) {
  if (!container || !market) return;
  const rawBook = snap.orderbooks?.[market.ticker] || null;
  const norm = normalizeOrderbook(rawBook, market);
  const maxSize = Math.max(
    1,
    ...norm.yesBids.map((r) => r.size),
    ...norm.yesAsks.map((r) => r.size)
  );
  const srcUrl = rawBook?.source_url || `${DEMO_REST}/markets/${market.ticker}/orderbook?depth=10`;
  const asksTopDown = [...norm.yesAsks].reverse();

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-size:12px;">
      <span>Source: <span class="mono">${norm.sourceType === "orderbook_fp" ? "Full /orderbook_fp" : "Market Top-of-Book"}</span> · Fee Mult: <span class="mono">${market.fee_multiplier ?? 1}&times;</span></span>
      <a href="${esc(srcUrl)}" target="_blank" rel="noopener">Verify Orderbook JSON ↗</a>
    </div>
    <div style="font-size:11px;color:var(--muted);margin-bottom:4px;">IMPLIED YES ASKS ($1.00 &minus; NO Bid) · Contracts Available</div>
    ${
      asksTopDown.length
        ? asksTopDown
            .map(
              (a) => `
          <div class="book-row">
            <span class="down-txt">$${a.price.toFixed(4)}</span>
            <div><div class="book-bar ask" style="width:${Math.max(4, (a.size / maxSize) * 100)}%"></div></div>
            <span style="text-align:right">${fmtNum(a.size, 2)}</span>
          </div>`
            )
            .join("")
        : `<div class="subnote" style="margin:4px 0;">No resting NO bids (no implied YES ask &lt; $1.00).</div>`
    }
    <div style="padding:6px 8px;margin:6px 0;background:#0b111e;border:1px solid var(--line);border-radius:6px;font-family:var(--mono);font-size:12px;display:flex;justify-content:space-between;">
      <span>Best Bid: ${norm.bestYesBid !== null ? `$${norm.bestYesBid.toFixed(4)}` : "—"}</span>
      <span>Spread: ${norm.spread !== null ? `$${norm.spread.toFixed(4)}` : "—"}</span>
      <span>Best Ask: ${norm.bestYesAsk !== null ? `$${norm.bestYesAsk.toFixed(4)}` : "—"}</span>
    </div>
    <div style="font-size:11px;color:var(--muted);margin-bottom:4px;">RESTING YES BIDS (Sorted Best Bid First) · Contracts Available</div>
    ${
      norm.yesBids.length
        ? norm.yesBids
            .map(
              (b) => `
          <div class="book-row">
            <span class="up-txt">$${b.price.toFixed(4)}</span>
            <div><div class="book-bar bid" style="width:${Math.max(4, (b.size / maxSize) * 100)}%"></div></div>
            <span style="text-align:right">${fmtNum(b.size, 2)}</span>
          </div>`
            )
            .join("")
        : `<div class="subnote" style="margin:4px 0;">No resting YES bids.</div>`
    }
  `;
}

function renderVwapPreview(previewEl, snap, state) {
  if (!previewEl) return;
  const tickerEl = document.getElementById("quick-ticker");
  const sideEl = document.getElementById("quick-side");
  const contractsEl = document.getElementById("quick-contracts");
  if (!tickerEl || !sideEl || !contractsEl) return;

  const ticker = tickerEl.value;
  const side = sideEl.value || "yes";
  const contracts = Math.max(1, Number(contractsEl.value || 10));
  const market = snap.markets.find((m) => m.ticker === ticker) || snap.markets[0];
  if (!market) return;

  const rawBook = snap.orderbooks?.[market.ticker] || null;
  const norm = normalizeOrderbook(rawBook, market);
  const est = estimateOrderbookFill(norm, side, contracts);
  const fallbackYes = Number(market.last_price_dollars || market.yes_ask_dollars || 0.5);
  const execPrice =
    est.vwapPrice !== null
      ? est.vwapPrice
      : Math.min(0.99, Math.max(0.01, side === "yes" ? fallbackYes : Number((1 - fallbackYes).toFixed(4))));
  const feeMult = market.fee_multiplier !== undefined ? Number(market.fee_multiplier) : 1;
  const raw6dp = rawTakerFee6dp(contracts, execPrice, 0.07, feeMult);
  const feeStep = applyFeeAccumulator(raw6dp, state.feeAccumulator, true, -(contracts * execPrice));

  if (est.vwapPrice !== null) {
    previewEl.innerHTML = `
      <span class="mono">Depth Preview (${esc(side.toUpperCase())} &times; ${contracts}):</span>
      VWAP <strong>$${est.vwapPrice.toFixed(4)}</strong> across ${est.levelsWalked} level(s)
      (slippage ${est.slippage >= 0 ? "+" : ""}$${est.slippage.toFixed(4)}, resting depth ${fmtNum(est.totalDepth, 2)}${est.unfilledContracts > 0 ? `, <span class="down-txt">${fmtNum(est.unfilledContracts, 0)} unfilled</span>` : ""}) ·
      6dp Fee <span class="mono">$${raw6dp.toFixed(6)}</span> (debit <span class="mono">$${feeStep.charged.toFixed(4)}</span>)
    `;
  } else {
    previewEl.innerHTML = `
      <span class="mono">Mark Preview (${esc(side.toUpperCase())} &times; ${contracts}):</span>
      No resting ${esc(side.toUpperCase())} ask liquidity &lt; $1.00 — simulated fill marks at last print <strong>$${execPrice.toFixed(4)}</strong> ·
      6dp Fee <span class="mono">$${raw6dp.toFixed(6)}</span> (debit <span class="mono">$${feeStep.charged.toFixed(4)}</span>)
    `;
  }
}

function renderAlertChats(allEl, selEl, swings, topicFilter) {
  const list = topicFilter && topicFilter !== "ALL" ? swings.filter((s) => s.topic === topicFilter) : swings;
  if (allEl) {
    allEl.innerHTML = list.length
      ? list
          .map(
            (s) => `
        <div class="chat-msg ${s.direction}">
          <div class="meta">
            <span>[${esc(s.topic)}] <strong>${esc(s.ticker)}</strong></span>
            <span>${esc(String(s.ts).slice(11, 23) || s.ts)}</span>
          </div>
          <div>
            <strong>${s.delta > 0 ? "▲" : "▼"} ${s.delta > 0 ? "+" : ""}$${s.delta.toFixed(2)}</strong>
            ($${Number(s.prev_price).toFixed(3)} &rarr; $${Number(s.new_price).toFixed(3)}) · ${esc(s.title)}
          </div>
          <div style="font-size:11.5px;color:var(--muted);margin-top:2px;">${esc(s.selective_reason)}</div>
          <div class="links">
            <a href="${esc(s.api_url)}" target="_blank" rel="noopener">Kalshi Demo API ↗</a>
            <a href="${esc(s.catalyst_url)}" target="_blank" rel="noopener">${esc(s.catalyst_label)} ↗</a>
          </div>
        </div>`
          )
          .join("")
      : `<div class="subnote">No &ge;$0.10 swings recorded for this topic filter yet.</div>`;
  }

  if (selEl) {
    const highRoi = list.filter((s) => s.selective_pass);
    selEl.innerHTML = highRoi.length
      ? highRoi
          .map(
            (s) => `
        <div class="chat-msg ${s.direction}">
          <div class="meta">
            <span><span class="badge ok">Est. Net ROI +${s.net_roi_pct}%</span> <strong>${esc(s.ticker)}</strong></span>
            <span>${esc(String(s.ts).slice(11, 23) || s.ts)}</span>
          </div>
          <div>
            <strong>${s.delta > 0 ? "BUY YES" : "BUY NO"}</strong> on ${s.delta > 0 ? "+" : ""}$${s.delta.toFixed(2)} swing
            ($${Number(s.prev_price).toFixed(2)} &rarr; $${Number(s.new_price).toFixed(2)}) · Depth: ${fmtNum(s.depth_contracts, 0)} contracts
          </div>
          <div class="links">
            <a href="${esc(s.api_url)}" target="_blank" rel="noopener">Verify Trade Print JSON ↗</a>
            <a href="${esc(s.catalyst_url)}" target="_blank" rel="noopener">Reference Source ↗</a>
          </div>
        </div>`
          )
          .join("")
      : `<div class="subnote">Zero alerts passed the Selective High-ROI filter (net_roi &ge; 12%, spread &le; $0.08, depth &ge; 25) for this filter.</div>`;
  }
}

function renderTopicTables(container, snap, selectedTicker, topicFilter, onSelectMarket) {
  if (!container) return;
  const topicsToShow = topicFilter && topicFilter !== "ALL" ? [topicFilter] : ALLOWED_TOPICS;
  const blocks = [];

  for (const topic of topicsToShow) {
    const topicMarkets = snap.markets
      .filter((m) => m.topic === topic)
      .sort((a, b) => Number(b.volume_fp) - Number(a.volume_fp));

    const eventMap = new Map();
    for (const m of topicMarkets) {
      if (!eventMap.has(m.event_ticker)) {
        eventMap.set(m.event_ticker, {
          event_ticker: m.event_ticker,
          event_title: m.event_title,
          event_api_url: m.event_api_url,
          totalVol: 0,
          markets: []
        });
      }
      const g = eventMap.get(m.event_ticker);
      g.totalVol += Number(m.volume_fp || 0);
      g.markets.push(m);
    }

    const sortedEvents = [...eventMap.values()].sort((a, b) => b.totalVol - a.totalVol);

    blocks.push(`
      <div class="card">
        <h2>
          <span>${esc(topic)} — Highest-Volume Demo Events (${topicMarkets.length} Verified Open Contracts)</span>
          <span class="badge accent">Events Grouped Together</span>
        </h2>
        ${sortedEvents
          .map(
            (ev) => `
          <h3>
            Event: <span class="mono">${esc(ev.event_ticker)}</span> — ${esc(ev.event_title)}
            <span class="badge">Event Vol: ${fmtNum(ev.totalVol, 2)} contracts</span>
            <a href="${esc(ev.event_api_url)}" target="_blank" rel="noopener" style="font-size:12px;margin-left:8px;">Event API ↗</a>
          </h3>
          <div class="table-wrap" style="margin-bottom:12px;">
            <table>
              <thead>
                <tr>
                  <th>Contract Ticker</th>
                  <th>Outcome / Subtitle</th>
                  <th class="num">Last ($)</th>
                  <th class="num">YES Bid / Ask</th>
                  <th class="num">Top Liquidity (Bid/Ask)</th>
                  <th class="num">Total Vol (Contracts)</th>
                  <th class="num">Open Interest</th>
                  <th>Official Sources</th>
                </tr>
              </thead>
              <tbody>
                ${ev.markets
                  .map((m) => {
                    const isSel = m.ticker === selectedTicker;
                    return `
                  <tr class="clickable ${isSel ? "selected" : ""}" data-select-ticker="${esc(m.ticker)}">
                    <td class="mono"><strong>${esc(m.ticker)}</strong></td>
                    <td>${esc(m.subtitle || m.title)}</td>
                    <td class="num">$${Number(m.last_price_dollars).toFixed(4)}</td>
                    <td class="num">$${Number(m.yes_bid_dollars).toFixed(4)} / $${Number(m.yes_ask_dollars).toFixed(4)}</td>
                    <td class="num">${fmtNum(m.yes_bid_size_fp, 2)} / ${fmtNum(m.yes_ask_size_fp, 2)}</td>
                    <td class="num">${fmtNum(m.volume_fp, 2)}</td>
                    <td class="num">${fmtNum(m.open_interest_fp, 2)}</td>
                    <td>
                      <a href="${esc(m.api_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Kalshi API ↗</a> ·
                      <a href="${esc(m.settlement_source_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(m.settlement_source_name)} ↗</a>
                    </td>
                  </tr>`;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>`
          )
          .join("")}
      </div>
    `);
  }

  container.innerHTML = blocks.join("");
  container.querySelectorAll("[data-select-ticker]").forEach((row) => {
    row.addEventListener("click", () => onSelectMarket(row.getAttribute("data-select-ticker")));
  });
}

export async function bootLivePage(config = {}) {
  const dataPath = config.dataPath || "./data/verified_snapshot.json";
  const pageTopic = config.topic || "ALL";
  const resp = await fetch(dataPath);
  const snap = await resp.json();
  const state = loadState();
  seedInitialPortfolioIfNeeded(state, snap);

  let activeTopic = pageTopic;
  let windowMode = "seconds";
  let liveSwings = [...snap.swings];
  const initialCandidates =
    activeTopic === "ALL" ? snap.markets : snap.markets.filter((m) => m.topic === activeTopic);
  let selectedTicker =
    (initialCandidates.find((m) => m.ticker === "KXDEMOFUTHOURLY-26NOV27H20-UP") ||
      initialCandidates[0] ||
      snap.markets[0])?.ticker;

  const updateTopKpis = () => {
    const metrics = computePortfolioMetrics(state, snap);
    const setTxt = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    setTxt("kpi-demo-status", snap.environment.exchange_active ? "ACTIVE (4 Shards)" : "INACTIVE");
    setTxt("kpi-open-count", String(snap.markets.length));
    setTxt("kpi-swing-count", `${liveSwings.length} (${liveSwings.filter((s) => s.selective_pass).length} High-ROI)`);
    setTxt("kpi-equity", fmtUsd(metrics.equity));
    setTxt("kpi-pnl", `${metrics.netPnl >= 0 ? "+" : ""}${fmtUsd(metrics.netPnl)}`);
    setTxt("kpi-fees", fmtUsd(state.totalFeesCharged, 4));
  };

  const renderMainDashboard = () => {
    updateTopKpis();
    const market = snap.markets.find((m) => m.ticker === selectedTicker) || snap.markets[0];
    const selLabel = document.getElementById("selected-market-label");
    if (selLabel && market) {
      selLabel.innerHTML = `<span class="mono">${esc(market.ticker)}</span> — ${esc(market.title)} <a href="${esc(market.api_url)}" target="_blank" rel="noopener">API JSON ↗</a>`;
    }
    const canvas = document.getElementById("price-chart");
    const tooltip = document.getElementById("chart-tooltip");
    if (canvas && market) {
      const pts = buildChartSeries(snap, market, windowMode);
      drawPriceChart(canvas, tooltip, pts, market);
    }
    renderOrderbookPanel(document.getElementById("orderbook-panel"), snap, market);
    renderVwapPreview(document.getElementById("quick-vwap-preview"), snap, state);
    renderAlertChats(
      document.getElementById("chat-all"),
      document.getElementById("chat-selective"),
      liveSwings,
      activeTopic
    );
    renderTopicTables(
      document.getElementById("topic-tables"),
      snap,
      selectedTicker,
      activeTopic,
      (ticker) => {
        selectedTicker = ticker;
        const ticketSel = document.getElementById("quick-ticker");
        if (ticketSel) ticketSel.value = ticker;
        renderMainDashboard();
      }
    );
  };

  async function refreshLiveDemoData() {
    const statusBadge = document.getElementById("conn-badge");
    if (statusBadge) statusBadge.textContent = "Polling Live Kalshi Demo REST...";
    try {
      const stRes = await fetchDemoPublicJson("/exchange/status");
      snap.environment.exchange_active = Boolean(stRes.data?.exchange_active);

      // Refresh watched market quotes & detect real-time >=$0.10 swings + finalized resolutions
      const tickersCsv = snap.markets.map((m) => m.ticker).join(",");
      const mktsRes = await fetchDemoPublicJson(`/markets?tickers=${encodeURIComponent(tickersCsv)}&limit=100`);
      const liveMarkets = Array.isArray(mktsRes.data?.markets) ? mktsRes.data.markets : [];
      let newSwingCount = 0;
      let newlyFinalized = 0;

      for (const lm of liveMarkets) {
        const local = snap.markets.find((x) => x.ticker === lm.ticker);
        if (!local) continue;
        const prevLast = Number(local.last_price_dollars || 0);
        const nextLast = Number(lm.last_price_dollars || prevLast);

        local.last_price_dollars = lm.last_price_dollars ?? local.last_price_dollars;
        local.yes_bid_dollars = lm.yes_bid_dollars ?? local.yes_bid_dollars;
        local.yes_ask_dollars = lm.yes_ask_dollars ?? local.yes_ask_dollars;
        local.yes_bid_size_fp = lm.yes_bid_size_fp ?? local.yes_bid_size_fp;
        local.yes_ask_size_fp = lm.yes_ask_size_fp ?? local.yes_ask_size_fp;
        local.volume_fp = lm.volume_fp ?? local.volume_fp;
        local.volume_24h_fp = lm.volume_24h_fp ?? local.volume_24h_fp;
        local.open_interest_fp = lm.open_interest_fp ?? local.open_interest_fp;
        local.status = lm.status ?? local.status;

        if (prevLast > 0 && nextLast > 0) {
          const yb = Number(local.yes_bid_dollars || 0);
          const ya = Number(local.yes_ask_dollars || 1);
          const sp = ya >= yb && ya > 0 ? Number((ya - yb).toFixed(4)) : 1.0;
          const depth = Number(local.yes_bid_size_fp || 0) + Number(local.yes_ask_size_fp || 0);
          const sw = evaluateSwing({
            ticker: local.ticker,
            topic: local.topic,
            title: `${local.title} [Live Poll]`,
            prevPrice: prevLast,
            newPrice: nextLast,
            spread: sp,
            depthContracts: depth,
            feeMultiplier: local.fee_multiplier ?? 1,
            ts: new Date().toISOString(),
            apiUrl: local.api_url,
            catalystLabel: `${local.settlement_source_name} (Live Demo Poll)`,
            catalystUrl: local.settlement_source_url
          });
          if (sw) {
            liveSwings.unshift(sw);
            newSwingCount += 1;
            const sigs = generateStrategySignals(sw, state.enabledStrategies, state.customStrategies);
            sigs.forEach((sig) =>
              recordTrade(state, {
                ...sig,
                ts: sw.ts,
                ticker: sw.ticker,
                topic: sw.topic,
                fee_multiplier: local.fee_multiplier ?? 1,
                source_url: sw.api_url
              })
            );
          }
        }

        if (lm.status === "finalized" && lm.result) {
          newlyFinalized += settleTradesForMarket(state, lm.ticker, lm.result, lm.settlement_value_dollars);
        }
      }

      // Refresh selected contract orderbook & recent trade prints for chart
      const selMarket = snap.markets.find((m) => m.ticker === selectedTicker) || snap.markets[0];
      if (selMarket) {
        try {
          const obRes = await fetchDemoPublicJson(
            `/markets/${encodeURIComponent(selMarket.ticker)}/orderbook?depth=10`
          );
          const obFp = obRes.data?.orderbook_fp || obRes.data?.orderbook;
          if (obFp) {
            snap.orderbooks = snap.orderbooks || {};
            snap.orderbooks[selMarket.ticker] = {
              source_url: `${DEMO_REST}/markets/${selMarket.ticker}/orderbook?depth=10`,
              yes_dollars: obFp.yes_dollars || [],
              no_dollars: obFp.no_dollars || []
            };
          }
        } catch {
          // Keep snapshot orderbook if individual call fails
        }
        try {
          const trRes = await fetchDemoPublicJson(
            `/markets/trades?ticker=${encodeURIComponent(selMarket.ticker)}&limit=15`
          );
          const prints = Array.isArray(trRes.data?.trades) ? [...trRes.data.trades].reverse() : [];
          if (prints.length >= 2) {
            snap.series_history = snap.series_history || {};
            snap.series_history[selMarket.ticker] = snap.series_history[selMarket.ticker] || {};
            snap.series_history[selMarket.ticker].seconds = prints.map((p) => ({
              ts: p.created_time,
              price: Number(p.yes_price_dollars || 0),
              count: Number(p.count_fp || 0),
              taker_side: p.taker_side,
              trade_id: p.trade_id,
              source_url: `${DEMO_REST}/markets/trades?ticker=${selMarket.ticker}&limit=15`,
              catalyst_url: selMarket.settlement_source_url
            }));
          }
        } catch {
          // Keep snapshot trades if individual call fails
        }
      }

      if (newSwingCount > 0 || newlyFinalized > 0) saveState(state);
      renderMainDashboard();
      renderPortfolioPage();

      if (statusBadge) {
        const nowStr = new Date().toISOString().slice(11, 19) + "Z";
        statusBadge.textContent = `Live Demo REST Synced ${nowStr} (${liveMarkets.length} mkts${newSwingCount ? `, +${newSwingCount} swing` : ""})`;
        statusBadge.className = "badge ok";
      }
    } catch (err) {
      if (statusBadge) {
        statusBadge.textContent = `Live Fetch Fallback (${err.message}) — Serving Verified Snapshot`;
        statusBadge.className = "badge warn";
      }
    }
  }

  document.querySelectorAll("[data-window]").forEach((btn) => {
    btn.addEventListener("click", () => {
      windowMode = btn.getAttribute("data-window");
      document.querySelectorAll("[data-window]").forEach((b) => b.classList.toggle("active", b === btn));
      renderMainDashboard();
    });
  });

  document.querySelectorAll("[data-topic-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTopic = btn.getAttribute("data-topic-filter");
      document.querySelectorAll("[data-topic-filter]").forEach((b) => b.classList.toggle("active", b === btn));
      const pool = activeTopic === "ALL" ? snap.markets : snap.markets.filter((m) => m.topic === activeTopic);
      if (pool.length && !pool.some((m) => m.ticker === selectedTicker)) {
        selectedTicker = pool[0].ticker;
      }
      renderMainDashboard();
    });
  });

  const replayTicker =
    Object.keys(snap.series_history || {}).find((k) => snap.series_history[k]?.seconds?.length >= 2) ||
    "KXDEMOFUTHOURLY-26NOV27H20-UP";
  const replayBtn = document.getElementById("btn-replay-tape");
  let replayTimer = null;
  if (replayBtn) {
    replayBtn.addEventListener("click", () => {
      if (replayTimer) {
        clearInterval(replayTimer);
        replayTimer = null;
      }
      const ticks = snap.series_history?.[replayTicker]?.seconds || [];
      if (ticks.length < 2) return;
      selectedTicker = replayTicker;
      windowMode = "seconds";
      let idx = 1;
      const statusBadge = document.getElementById("conn-badge");
      if (statusBadge) statusBadge.textContent = `Replaying Verified 5s Demo Prints (${replayTicker})...`;
      replayTimer = setInterval(() => {
        if (idx >= ticks.length) {
          clearInterval(replayTimer);
          replayTimer = null;
          if (statusBadge) statusBadge.textContent = "Verified Demo Snapshot + 5s Replay Complete";
          return;
        }
        const prev = ticks[idx - 1];
        const curr = ticks[idx];
        const sw = evaluateSwing({
          ticker: replayTicker,
          topic: "Crypto",
          title: `Demo hourly BTC price [Replay ${curr.trade_id ? curr.trade_id.slice(0, 8) : ""}]`,
          prevPrice: prev.price,
          newPrice: curr.price,
          spread: 0.06,
          depthContracts: 90.0,
          ts: curr.ts,
          apiUrl: curr.source_url,
          catalystLabel: "Coinbase BTC-USD Candles (Verified 5s Trade Print)",
          catalystUrl: curr.catalyst_url
        });
        if (sw) {
          liveSwings.unshift(sw);
          const sigs = generateStrategySignals(sw, state.enabledStrategies, state.customStrategies);
          sigs.forEach((sig) =>
            recordTrade(state, {
              ...sig,
              ts: sw.ts,
              ticker: sw.ticker,
              topic: sw.topic,
              source_url: sw.api_url
            })
          );
          saveState(state);
        }
        idx += 1;
        renderMainDashboard();
      }, 650);
    });
  }

  const pollBtn = document.getElementById("btn-poll-demo");
  if (pollBtn) {
    pollBtn.addEventListener("click", () => {
      refreshLiveDemoData();
    });
  }

  const autoPollBtn = document.getElementById("btn-autopoll-demo");
  let autoPollTimer = null;
  if (autoPollBtn) {
    autoPollBtn.addEventListener("click", () => {
      if (autoPollTimer) {
        clearInterval(autoPollTimer);
        autoPollTimer = null;
        autoPollBtn.classList.remove("active");
        autoPollBtn.textContent = "Auto-Poll (20s): OFF";
      } else {
        autoPollBtn.classList.add("active");
        autoPollBtn.textContent = "Auto-Poll (20s): ON";
        refreshLiveDemoData();
        autoPollTimer = setInterval(refreshLiveDemoData, 20000);
      }
    });
  }

  const quickTicker = document.getElementById("quick-ticker");
  if (quickTicker) {
    quickTicker.innerHTML = snap.markets
      .map(
        (m) =>
          `<option value="${esc(m.ticker)}" ${m.ticker === selectedTicker ? "selected" : ""}>${esc(m.ticker)} (${esc(m.topic)} · $${Number(m.last_price_dollars).toFixed(3)})</option>`
      )
      .join("");
    quickTicker.addEventListener("change", () => {
      selectedTicker = quickTicker.value;
      renderMainDashboard();
    });
  }
  ["quick-side", "quick-contracts"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", () => renderVwapPreview(document.getElementById("quick-vwap-preview"), snap, state));
    if (el) el.addEventListener("change", () => renderVwapPreview(document.getElementById("quick-vwap-preview"), snap, state));
  });

  const quickForm = document.getElementById("quick-order-form");
  if (quickForm) {
    quickForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const ticker = document.getElementById("quick-ticker").value;
      const side = document.getElementById("quick-side").value;
      const contracts = Math.max(1, Number(document.getElementById("quick-contracts").value || 10));
      const m = snap.markets.find((x) => x.ticker === ticker) || snap.markets[0];
      const rawBook = snap.orderbooks?.[m.ticker] || null;
      const norm = normalizeOrderbook(rawBook, m);
      const est = estimateOrderbookFill(norm, side, contracts);
      const yesPrice = Number(m.last_price_dollars || m.yes_ask_dollars || 0.50);
      const price =
        est.vwapPrice !== null
          ? est.vwapPrice
          : Math.min(0.99, Math.max(0.01, side === "yes" ? yesPrice : Number((1 - yesPrice).toFixed(4))));
      const msgEl = document.getElementById("quick-order-msg");

      let relayInfo = "";
      const relayCheckbox = document.getElementById("quick-send-relay");
      if (relayCheckbox?.checked) {
        try {
          const r = await fetch(resolveApiPath("/api/demo/order"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker, side, action: "buy", contracts, price_dollars: price.toFixed(4) })
          });
          const j = await r.json();
          relayInfo = j.ok
            ? ` · Live V2 Demo order submitted (${esc(j.order?.order?.order_id || "accepted")})`
            : ` · Relay note: ${esc(j.error || "no Demo keys configured; recorded in local simulation")}`;
        } catch {
          relayInfo = " · Static Pages mode (no server relay; recorded in local simulation)";
        }
      }

      const tr = recordTrade(state, {
        ticker,
        topic: m.topic,
        strategy_id: "manual_ticket",
        strategy_label: "Manual Demo Ticket",
        trade_type: "manual_discretionary",
        side,
        contracts,
        price,
        fee_multiplier: m.fee_multiplier ?? 1,
        source_url: m.api_url
      });
      saveState(state);
      if (msgEl) {
        msgEl.innerHTML = tr
          ? `<span class="up-txt">Executed simulated Demo fill: BUY ${tr.contracts} ${tr.side.toUpperCase()} @ $${tr.price.toFixed(4)} on ${esc(tr.ticker)} (6dp fee $${tr.fee_raw_6dp.toFixed(6)}, aligned debit $${tr.fee_charged.toFixed(4)})${relayInfo}.</span>`
          : `<span class="down-txt">Insufficient simulated cash balance.</span>`;
      }
      renderMainDashboard();
      renderPortfolioPage();
    });
  }

  const checkDemoBtn = document.getElementById("btn-check-demo-account");
  if (checkDemoBtn) {
    checkDemoBtn.addEventListener("click", async () => {
      const box = document.getElementById("demo-account-status-panel");
      if (!box) return;
      box.textContent = "Checking same-origin /api/demo/status...";
      try {
        const res = await fetch(resolveApiPath("/api/demo/status"), { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        if (d.authenticated && d.balance) {
          const cents = Number(d.balance.balance ?? 0);
          const portCents = Number(d.balance.portfolio_value ?? 0);
          const fillsCount = Array.isArray(d.fills?.fills) ? d.fills.fills.length : 0;
          box.innerHTML = `<span class="up-txt">Connected to Authenticated Kalshi Demo Account:</span> Cash <strong>$${(cents / 100).toFixed(2)}</strong> · Portfolio Value <strong>$${(portCents / 100).toFixed(2)}</strong> · Recent Fills: <strong>${fillsCount}</strong>`;
          const kpiAuth = document.getElementById("kpi-auth-balance");
          if (kpiAuth) kpiAuth.textContent = `$${(cents / 100).toFixed(2)}`;
        } else {
          box.innerHTML = `<span class="badge warn">Public Relay Active (Unauthenticated)</span> ${esc(d.auth_note || "Set KALSHI_DEMO_KEY_ID and KALSHI_DEMO_KEY_PATH locally to enable signed Demo Account reads.")}`;
        }
      } catch {
        box.innerHTML = `<span class="badge warn">Static GitHub Pages Mode</span> No local signed relay detected at <span class="mono">/api/demo/status</span>; authenticated Demo balance remains unverified (blank on Flagged F1) while simulated paper trading runs locally.`;
      }
    });
  }

  const renderPortfolioPage = () => {
    const stratTogglesEl = document.getElementById("strategy-toggles");
    if (!stratTogglesEl) return;
    updateTopKpis();
    const metrics = computePortfolioMetrics(state, snap);

    stratTogglesEl.innerHTML = Object.values(BUILTIN_STRATEGIES)
      .map((s) => {
        const checked = state.enabledStrategies.includes(s.id) ? "checked" : "";
        return `
        <label style="display:block;padding:8px 10px;border:1px solid var(--line);border-radius:8px;margin-bottom:8px;background:var(--panel-alt);cursor:pointer;">
          <input type="checkbox" data-strat-toggle="${esc(s.id)}" ${checked}>
          <strong>${esc(s.label)}</strong> <span class="badge">${esc(s.trade_type)}</span>
          <div style="font-size:12px;color:var(--muted);margin-top:2px;">${esc(s.description)}</div>
        </label>`;
      })
      .join("");

    stratTogglesEl.querySelectorAll("[data-strat-toggle]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const id = cb.getAttribute("data-strat-toggle");
        if (cb.checked && !state.enabledStrategies.includes(id)) state.enabledStrategies.push(id);
        if (!cb.checked) state.enabledStrategies = state.enabledStrategies.filter((x) => x !== id);
        saveState(state);
      });
    });

    const customListEl = document.getElementById("custom-strategies-list");
    if (customListEl) {
      customListEl.innerHTML = state.customStrategies.length
        ? state.customStrategies
            .map(
              (cs) => `
          <tr>
            <td><strong>${esc(cs.name)}</strong></td>
            <td><span class="badge accent">${esc(cs.trade_type)}</span></td>
            <td>${esc(cs.topic)} · dir=${esc(cs.direction)} · |Δ|&ge;$${Number(cs.min_abs_delta).toFixed(2)} · [$${Number(cs.min_price).toFixed(2)}, $${Number(cs.max_price).toFixed(2)}]</td>
            <td class="mono">${esc(cs.side.toUpperCase())} &times; ${cs.contracts}</td>
            <td><a href="https://docs.kalshi.com/getting_started/fee_rounding" target="_blank" rel="noopener">6dp Fee Spec ↗</a></td>
          </tr>`
            )
            .join("")
        : `<tr><td colspan="5">No custom strategies added yet. <a href="https://docs.kalshi.com/getting_started/fee_rounding" target="_blank" rel="noopener">6dp Fee Spec ↗</a></td></tr>`;
    }

    const byStratBody = document.getElementById("analytics-by-strategy");
    if (byStratBody) {
      byStratBody.innerHTML = metrics.byStrategy
        .map(
          (r) => `
        <tr>
          <td><strong>${esc(r.label)}</strong></td>
          <td class="num">${r.trades}</td>
          <td class="num">${r.contracts}</td>
          <td class="num">${fmtUsd(r.notional)}</td>
          <td class="num">${fmtUsd(r.fees, 4)}</td>
          <td class="num ${r.pnl >= 0 ? "up-txt" : "down-txt"}">${r.pnl >= 0 ? "+" : ""}${fmtUsd(r.pnl)}</td>
          <td class="num">${r.trades ? ((r.wins / r.trades) * 100).toFixed(0) : "0"}%</td>
          <td><a href="https://docs.kalshi.com/getting_started/fee_rounding" target="_blank" rel="noopener">Kalshi Fee Spec ↗</a></td>
        </tr>`
        )
        .join("");
    }

    const byTypeBody = document.getElementById("analytics-by-type");
    if (byTypeBody) {
      byTypeBody.innerHTML = metrics.byType
        .map(
          (r) => `
        <tr>
          <td><span class="badge accent">${esc(r.label)}</span></td>
          <td class="num">${r.trades}</td>
          <td class="num">${r.contracts}</td>
          <td class="num">${fmtUsd(r.notional)}</td>
          <td class="num">${fmtUsd(r.fees, 4)}</td>
          <td class="num ${r.pnl >= 0 ? "up-txt" : "down-txt"}">${r.pnl >= 0 ? "+" : ""}${fmtUsd(r.pnl)}</td>
          <td class="num">${r.trades ? ((r.wins / r.trades) * 100).toFixed(0) : "0"}%</td>
          <td><a href="https://docs.kalshi.com/getting_started/quick_start_create_order" target="_blank" rel="noopener">V2 Order Spec ↗</a></td>
        </tr>`
        )
        .join("");
    }

    const ledgerBody = document.getElementById("trade-ledger-body");
    if (ledgerBody) {
      ledgerBody.innerHTML = state.trades
        .slice(0, 40)
        .map(
          (t) => `
        <tr>
          <td class="mono">${esc(String(t.ts).slice(0, 19))}Z</td>
          <td class="mono"><strong>${esc(t.ticker)}</strong></td>
          <td>${esc(t.topic)}</td>
          <td>${esc(t.strategy_label)}</td>
          <td><span class="badge">${esc(t.trade_type)}</span></td>
          <td class="mono">${esc(t.side.toUpperCase())} &times; ${t.contracts} @ $${t.price.toFixed(4)}</td>
          <td class="num">$${t.fee_charged.toFixed(4)}</td>
          <td>${t.settled ? `<span class="badge ok">Finalized (${esc(t.settlement_result)}) ${t.realized_pnl >= 0 ? "+" : ""}${fmtUsd(t.realized_pnl)}</span>` : `<span class="badge warn">Open</span>`}</td>
          <td><a href="${esc(t.source_url)}" target="_blank" rel="noopener">Market API ↗</a></td>
        </tr>`
        )
        .join("");
    }
  };

  const customForm = document.getElementById("custom-strategy-form");
  if (customForm) {
    customForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const name = document.getElementById("cs-name").value.trim() || "Custom Rule";
      const trade_type = document.getElementById("cs-type").value;
      const topic = document.getElementById("cs-topic").value;
      const direction = document.getElementById("cs-dir").value;
      const side = document.getElementById("cs-side").value;
      const min_abs_delta = Math.max(0.10, Number(document.getElementById("cs-delta").value || 0.10));
      const min_price = Number(document.getElementById("cs-minp").value || 0.05);
      const max_price = Number(document.getElementById("cs-maxp").value || 0.95);
      const contracts = Math.max(1, Number(document.getElementById("cs-contracts").value || 10));

      const cs = {
        id: `cs_${Date.now()}`,
        name,
        trade_type,
        topic,
        direction,
        side,
        min_abs_delta,
        min_price,
        max_price,
        contracts,
        enabled: true
      };
      state.customStrategies.push(cs);
      for (const sw of [...snap.swings].reverse()) {
        const sigs = generateStrategySignals(sw, [], [cs]);
        sigs.forEach((sig) =>
          recordTrade(state, {
            ...sig,
            ts: sw.ts,
            ticker: sw.ticker,
            topic: sw.topic,
            source_url: sw.api_url
          })
        );
      }
      saveState(state);
      renderPortfolioPage();
    });
  }

  const resetBtn = document.getElementById("btn-reset-ledger");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      localStorage.removeItem(STORAGE_KEY);
      const fresh = defaultState();
      seedInitialPortfolioIfNeeded(fresh, snap);
      Object.assign(state, fresh);
      renderPortfolioPage();
      renderMainDashboard();
    });
  }

  renderMainDashboard();
  renderPortfolioPage();
}
