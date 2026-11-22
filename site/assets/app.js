/* Kalshi Demo Dashboard — vanilla JS, no build step.
   Live data: Kalshi demo REST (public endpoints, fetched from visitor browser).
   Fallback: clearly-labeled simulated data if API unreachable / CORS blocked.
   Sources: https://docs.kalshi.com/getting_started/demo_env
            https://docs.kalshi.com/api-reference/market/get-markets
            https://docs.kalshi.com/api-reference/market/get-market-orderbook */
"use strict";

/* ---------- Config ---------- */
const DEMO_BASE = "https://external-api.demo.kalshi.co/trade-api/v2";
const DEMO_BASE_ALT = "https://demo-api.kalshi.co/trade-api/v2";
const PROD_BASE = "https://external-api.kalshi.com/trade-api/v2";
const POLL_MS = 8000;              // polling interval (WS needs API-key auth; see Methodology)
const ALERT_THRESHOLD = 0.10;      // $0.10 swing, either direction (task requirement)
const ROI_SCORE_MIN = 60;          // model score >= 60 => "high ROI" chat
const MAX_PAGES = 3, PAGE_LIMIT = 200;

/* Topics: keyword heuristic over ticker/title/event_ticker.
   UNVERIFIED (sandbox cannot reach *.kalshi.co) — review on Flagged page. */
const TOPICS = {
  "Gas Prices": { keys: ["GAS", "GASPRICE", "OIL", "FUEL", "GASOLINE", "CRUDE", "ENERGY"], color: "#f5a623" },
  "Elections":  { keys: ["ELECTION", "SENATE", "HOUSE", "GOVERNOR", "PRESIDENT", "VOTE", "CONGRESS", "BALLOT", "MAYOR"], color: "#4c9aff" },
  "Culture":    { keys: ["CULTURE", "MOVIE", "FILM", "OSCAR", "GRAMMY", "EMMY", "BOOK", "CELEB", "ENTERTAIN", "AWARD", "MUSIC", "TV", "STREAM"], color: "#b07fe8" },
  "Crypto":     { keys: ["CRYPTO", "BITCOIN", "BTC", "ETH", "ETHEREUM", "SOL", "DOGE", "COIN", "TOKEN", "BLOCKCHAIN"], color: "#00b67a" },
  "Golf":       { keys: ["GOLF", "PGA", "MASTERS", "OPEN", "RYDER", "LIV", "GOLFER"], color: "#7bc96f" }
};
const TOPIC_SOURCES = { // curated official links to CHECK after a jump — NOT causal claims
  "Gas Prices": [["EIA Petroleum & Other Liquids", "https://www.eia.gov/petroleum/supply/weekly/"]],
  "Elections": [["Kalshi Elections", "https://kalshi.com/"]],
  "Culture": [["Kalshi Culture", "https://kalshi.com/"]],
  "Crypto": [["Kalshi Crypto", "https://kalshi.com/"]],
  "Golf": [["PGA Tour", "https://www.pgatour.com/"]]
};

/* ---------- State ---------- */
const S = {
  mode: "live",            // "live" | "sim"
  base: DEMO_BASE,
  markets: new Map(),      // ticker -> market object (normalized)
  history: new Map(),      // ticker -> [{t, p}]
  alerts: [],              // {t, ticker, title, topic, from, to, delta, score}
  resolutions: [],         // {t, ticker, title, topic, result}
  selected: null,          // selected ticker for chart/orderbook
  topicFilter: "All",
  windowMs: 3600_000,      // chart window: 1h default; buttons: 60s/5m/1h/24h
  sim: null,               // simulated engine state
  paper: { cash: 1000, positions: [], trades: [], equity: [] },
  strategies: { momentum: true, meanrev: true, favorite: false, longshot: false },
  bankroll: 1000, contractsPerTrade: 10,
  timer: null, connected: false
};

/* ---------- Helpers ---------- */
const $ = id => document.getElementById(id);
const fmt$ = v => (v == null || isNaN(v)) ? "—" : "$" + Number(v).toFixed(2);
const fmtC = v => (v == null || isNaN(v)) ? "—" : Number(v).toFixed(2);
const now = () => Date.now();
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = v => { const n = parseFloat(v); return isNaN(n) ? null : n; };

function topicOf(m) {
  const hay = ((m.ticker || "") + " " + (m.event_ticker || "") + " " + (m.title || "") + " " + (m.subtitle || "")).toUpperCase();
  for (const [topic, cfg] of Object.entries(TOPICS))
    if (cfg.keys.some(k => hay.includes(k))) return topic;
  return null; // not one of the 5 topics -> excluded
}

/* Transparent heuristic model score 0-100 (documented on Methodology page).
   NOT a prediction guarantee. Inputs from public market fields only. */
function modelScore(m, momentum) {
  const vol = num(m.volume_fp) || 0, oi = num(m.open_interest_fp) || 0;
  const bid = num(m.yes_bid_dollars), ask = num(m.yes_ask_dollars), last = num(m.last_price_dollars);
  let s = 0;
  s += Math.min(30, Math.log10(vol + 1) * 10);          // liquidity/volume
  s += Math.min(20, Math.log10(oi + 1) * 8);            // open interest
  if (bid != null && ask != null && ask > 0) s += Math.max(0, 20 - (ask - bid) * 200); // tight spread
  if (last != null) s += Math.max(0, 20 - Math.abs(last - 0.5) * 40);                  // near coin-flip = most room to move
  if (momentum != null) s += Math.min(10, Math.abs(momentum) * 100);                  // recent move
  return Math.round(Math.min(100, s));
}

/* ---------- Simulated fallback data (labeled) ---------- */
function makeSim() {
  const seeds = [
    ["GASPRICE-26DEC", "Gas Prices", "National average gas price above $3.50?", 0.42],
    ["GASPRICE-26JAN", "Gas Prices", "Gas price above $4.00 this month?", 0.31],
    ["ELECTION-SENATE", "Elections", "Senate control after election?", 0.55],
    ["ELECTION-GOV", "Elections", "Governor race winner (Yes)?", 0.48],
    ["CULTURE-OSCAR", "Culture", "Best Picture winner (Yes)?", 0.38],
    ["CULTURE-GRAMMY", "Culture", "Album of the Year (Yes)?", 0.44],
    ["CRYPTO-BTC100K", "Crypto", "Bitcoin above $100k this month?", 0.52],
    ["CRYPTO-ETH4K", "Crypto", "Ethereum above $4,000 this month?", 0.36],
    ["GOLF-MASTERS", "Golf", "Defending champion wins Masters?", 0.29],
    ["GOLF-OPEN", "Golf", "World #1 wins The Open?", 0.33]
  ];
  const mk = () => seeds.map(([ticker, topic, title, p]) => ({
    ticker, event_ticker: ticker.split("-")[0], title, subtitle: "", topic,
    status: "open", last_price_dollars: p.toFixed(4),
    yes_bid_dollars: (p - 0.02).toFixed(4), yes_ask_dollars: (p + 0.02).toFixed(4),
    yes_bid_size_fp: "50.00", yes_ask_size_fp: "50.00",
    volume_fp: String(Math.round(500 + Math.random() * 9000)),
    open_interest_fp: String(Math.round(200 + Math.random() * 4000)),
    result: "", _p: p, _topic: topic
  }));
  return { markets: mk(), step() {
    for (const m of this.markets) {
      let d = (Math.random() - 0.5) * 0.04;
      if (Math.random() < 0.06) d += (Math.random() < 0.5 ? -1 : 1) * (0.10 + Math.random() * 0.08); // occasional >=$0.10 jump
      m._p = Math.min(0.97, Math.max(0.03, m._p + d));
      m.last_price_dollars = m._p.toFixed(4);
      m.yes_bid_dollars = (m._p - 0.02).toFixed(4); m.yes_ask_dollars = (m._p + 0.02).toFixed(4);
      m.volume_fp = String(Math.round(num(m.volume_fp) + Math.random() * 120));
      if (Math.random() < 0.01) { m.status = "settled"; m.result = Math.random() < m._p ? "yes" : "no"; }
    }
    return this.markets;
  }};
}

/* ---------- Data fetching ---------- */
async function fetchJSON(url) {
  const r = await fetch(url, { method: "GET" });
  if (!r.ok) throw new Error("HTTP " + r.status + " " + url);
  return r.json();
}
async function fetchLiveMarkets() {
  let cursor = "", out = [];
  for (let i = 0; i < MAX_PAGES; i++) {
    const q = new URLSearchParams({ status: "open", limit: PAGE_LIMIT });
    if (cursor) q.set("cursor", cursor);
    const j = await fetchJSON(`${S.base}/markets?${q}`);
    out = out.concat(j.markets || []);
    cursor = j.cursor || "";
    if (!cursor) break;
  }
  return out;
}
async function fetchOrderbook(ticker) {
  if (S.mode === "sim") { // synthetic depth around last price (labeled)
    const m = S.markets.get(ticker); const p = num(m?.last_price_dollars) ?? 0.5;
    const lvl = (base, n) => Array.from({ length: n }, (_, i) => [Math.min(0.99, Math.max(0.01, base + (i - n / 2) * 0.01)).toFixed(4), String(Math.round(10 + Math.random() * 200))]);
    return { orderbook_fp: { yes_dollars: lvl(p, 8), no_dollars: lvl(1 - p, 8) } };
  }
  return fetchJSON(`${S.base}/markets/${encodeURIComponent(ticker)}/orderbook?depth=10`);
}

/* ---------- Poll cycle ---------- */
async function poll() {
  let raw;
  try {
    raw = S.mode === "live" ? await fetchLiveMarkets() : S.sim.step();
    S.connected = true;
  } catch (e) {
    if (S.mode === "live") { setMode("sim", "Live API unreachable (" + e.message + ") — simulated data"); raw = S.sim.step(); }
    else raw = S.sim.step();
  }
  ingest(raw);
  renderAll();
}
function setMode(mode, reason) {
  S.mode = mode;
  if (mode === "sim" && !S.sim) S.sim = makeSim();
  const b = $("mode-banner");
  if (b) {
    b.className = "banner " + (mode === "sim" ? "sim" : "live");
    b.innerHTML = mode === "sim"
      ? "⚠️ <b>SIMULATED DATA</b> — " + esc(reason || "") + ". Live values unverified. Alerts/trades below use simulated prices."
      : "✅ <b>LIVE</b> — connected to Kalshi demo API (" + esc(S.base) + ").";
  }
  const badge = $("mode-badge");
  if (badge) { badge.textContent = mode === "sim" ? "SIMULATED" : "LIVE"; badge.className = "badge " + (mode === "sim" ? "badge-sim" : "badge-live"); }
}
function ingest(raw) {
  const seen = new Set();
  for (const m of raw) {
    const topic = m._topic || topicOf(m);
    if (!topic) continue;                       // only the 5 topics
    m.topic = topic;
    const ticker = m.ticker; seen.add(ticker);
    const prev = S.markets.get(ticker);
    const prevPrice = prev ? num(prev.last_price_dollars) : null;
    const price = num(m.last_price_dollars);
    // alert on >= $0.10 poll-to-poll move
    if (prevPrice != null && price != null && Math.abs(price - prevPrice) >= ALERT_THRESHOLD) {
      const delta = price - prevPrice;
      const score = modelScore(m, delta);
      const alert = { t: now(), ticker, title: m.title || ticker, topic, from: prevPrice, to: price, delta, score };
      S.alerts.unshift(alert); S.alerts = S.alerts.slice(0, 200);
      paperTradeOnAlert(alert, m);
    }
    // resolution tracking
    if (prev && prev.status !== "settled" && m.status === "settled" && (m.result === "yes" || m.result === "no")) {
      S.resolutions.unshift({ t: now(), ticker, title: m.title || ticker, topic, result: m.result });
      settlePositions(ticker, m.result);
    }
    S.markets.set(ticker, m);
    if (price != null) {
      const h = S.history.get(ticker) || [];
      if (!h.length || h[h.length - 1].p !== price) h.push({ t: now(), p: price });
      S.history.set(ticker, h.slice(-2000));
    }
  }
  // keep sim markets that settled visible briefly; live markets simply age out
  if (!S.selected || !S.markets.has(S.selected)) {
    const top = topMarkets(1)[0]; if (top) S.selected = top.ticker;
  }
}
function topMarkets(n) {
  let arr = [...S.markets.values()];
  if (S.topicFilter !== "All") arr = arr.filter(m => m.topic === S.topicFilter);
  return arr.sort((a, b) => ((num(b.volume_fp) || 0) + (num(b.open_interest_fp) || 0)) - ((num(a.volume_fp) || 0) + (num(a.open_interest_fp) || 0))).slice(0, n);
}

/* ---------- Paper trading engine ---------- */
function paperTradeOnAlert(alert, m) {
  const price = num(m.last_price_dollars); if (price == null) return;
  const preferred = alert.delta > 0 ? "momentum" : "meanrev";
  const other = preferred === "momentum" ? "meanrev" : "momentum";
  const strat = S.strategies[preferred] ? preferred : (S.strategies[other] ? other : null);
  if (!strat) return;
  const side = strat === "momentum" ? (alert.delta > 0 ? "yes" : "no") : (alert.delta > 0 ? "no" : "yes");
  const fill = side === "yes" ? price : 1 - price;
  const cost = fill * S.contractsPerTrade;
  if (S.paper.cash < cost) return;
  S.paper.cash -= cost;
  const pos = { id: "P" + now() + Math.floor(Math.random() * 999), ticker: alert.ticker, title: alert.title, topic: alert.topic, side, contracts: S.contractsPerTrade, fill, cost, strategy: strat, t: now(), status: "open" };
  S.paper.positions.unshift(pos);
  S.paper.trades.unshift({ ...pos, type: "OPEN" });
}
function settlePositions(ticker, result) {
  for (const p of S.paper.positions) {
    if (p.ticker === ticker && p.status === "open") {
      p.status = "closed"; p.result = result;
      p.payout = (p.side === result) ? p.contracts * 1.0 : 0;
      p.pnl = p.payout - p.cost;
      S.paper.cash += p.payout;
      S.paper.trades.unshift({ ...p, type: "SETTLE" });
    }
  }
}
function markToMarket() {
  let unreal = 0;
  for (const p of S.paper.positions) {
    if (p.status !== "open") continue;
    const m = S.markets.get(p.ticker); const last = num(m?.last_price_dollars);
    if (last == null) continue;
    const cur = p.side === "yes" ? last : 1 - last;
    unreal += cur * p.contracts - p.cost;
  }
  S.paper.equity.push({ t: now(), v: S.paper.cash + S.paper.positions.filter(p => p.status === "open").reduce((a, p) => a + p.cost, 0) + unreal });
  S.paper.equity = S.paper.equity.slice(-500);
  return unreal;
}

/* ---------- Rendering ---------- */
function renderAll() {
  renderTable(); renderChats(); renderChart(); renderOrderbook(); renderPortfolio(); renderResolutions();
  const st = $("status-line"); if (st) st.textContent = `Updated ${new Date().toLocaleTimeString()} · ${S.markets.size} markets in scope · ${S.alerts.length} alerts · mode: ${S.mode.toUpperCase()}`;
}
function renderTable() {
  const el = $("markets-table"); if (!el) return;
  const rows = topMarkets(30).map(m => {
    const last = num(m.last_price_dollars), bid = num(m.yes_bid_dollars), ask = num(m.yes_ask_dollars);
    const spread = (bid != null && ask != null) ? (ask - bid) : null;
    const score = modelScore(m, null);
    return `<tr data-ticker="${esc(m.ticker)}" class="${m.ticker === S.selected ? "sel" : ""}" style="cursor:pointer">
      <td><span class="badge badge-topic">${esc(m.topic)}</span></td>
      <td>${esc(m.title || m.ticker)}<br><span class="muted small">${esc(m.ticker)} · ${esc(m.event_ticker || "")}</span></td>
      <td>${fmt$(last)}</td><td>${fmt$(bid)} / ${fmt$(ask)}</td><td>${spread == null ? "—" : fmt$(spread)}</td>
      <td>${fmtC(num(m.volume_fp))}</td><td>${fmtC(num(m.open_interest_fp))}</td>
      <td>${score}${score >= ROI_SCORE_MIN ? " ⭐" : ""}</td>
      <td><a href="https://demo.kalshi.co/markets/${encodeURIComponent(m.ticker)}" target="_blank" rel="noopener">Kalshi ↗</a></td></tr>`;
  }).join("");
  el.innerHTML = `<table><thead><tr><th>Topic</th><th>Event / Market</th><th>Last</th><th>Bid/Ask</th><th>Spread</th><th>Volume</th><th>Open Int.</th><th>Model</th><th>Link</th></tr></thead><tbody>${rows || '<tr><td colspan="9" class="muted">No markets in scope yet…</td></tr>'}</tbody></table>`;
  el.querySelectorAll("tr[data-ticker]").forEach(tr => tr.onclick = () => { S.selected = tr.dataset.ticker; renderAll(); });
}
function chatMsg(a) {
  const dir = a.delta > 0 ? "▲" : "▼", cls = a.delta > 0 ? "up" : "down";
  const srcs = (TOPIC_SOURCES[a.topic] || []).map(([n, u]) => `<a href="${u}" target="_blank" rel="noopener">${esc(n)} ↗</a>`).join(" · ");
  return `<div class="msg"><span class="t">${new Date(a.t).toLocaleTimeString()}</span> <span class="${cls}">${dir} ${a.delta >= 0 ? "+" : ""}${a.delta.toFixed(2)}</span> <b>${esc(a.title)}</b> <span class="muted">(${esc(a.ticker)})</span> ${fmt$(a.from)} → ${fmt$(a.to)} · model ${a.score}<br><span class="muted small">Check catalysts: ${srcs || "—"}</span></div>`;
}
function renderChats() {
  const all = $("chat-all"), roi = $("chat-roi");
  if (all) all.innerHTML = S.alerts.map(chatMsg).join("") || '<div class="msg muted">Waiting for ≥ $0.10 swings…</div>';
  if (roi) roi.innerHTML = S.alerts.filter(a => a.score >= ROI_SCORE_MIN).map(chatMsg).join("") || '<div class="msg muted">No high-ROI (score ≥ ' + ROI_SCORE_MIN + ') alerts yet…</div>';
}
function renderResolutions() {
  const el = $("resolutions-table"); if (!el) return;
  el.innerHTML = `<table><thead><tr><th>Time</th><th>Topic</th><th>Event</th><th>Result</th></tr></thead><tbody>` +
    (S.resolutions.map(r => `<tr><td>${new Date(r.t).toLocaleTimeString()}</td><td>${esc(r.topic)}</td><td>${esc(r.title)} <span class="muted small">(${esc(r.ticker)})</span></td><td><b class="${r.result === "yes" ? "up" : "down"}">${esc(r.result.toUpperCase())}</b></td></tr>`).join("") || '<tr><td colspan="4" class="muted">No resolutions yet this session.</td></tr>') + `</tbody></table>`;
}
async function renderOrderbook() {
  const el = $("orderbook"); if (!el || !S.selected) return;
  try {
    const ob = await fetchOrderbook(S.selected);
    const y = ob.orderbook_fp?.yes_dollars || [], n = ob.orderbook_fp?.no_dollars || [];
    const rows = y.map((l, i) => `<tr><td>${fmt$(num(l[0]))}</td><td>${fmtC(num(l[1]))}</td><td>${fmt$(num(n[i]?.[0]))}</td><td>${fmtC(num(n[i]?.[1]))}</td></tr>`).join("");
    el.innerHTML = `<table><thead><tr><th>Yes price</th><th>Yes contracts</th><th>No price</th><th>No contracts</th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="muted">No depth returned.</td></tr>'}</tbody></table>`;
  } catch (e) { el.innerHTML = `<p class="muted small">Order book unavailable: ${esc(e.message)}</p>`; }
}
function renderChart() {
  const cv = $("price-chart"); if (!cv || !S.selected) return;
  const ctx = cv.getContext("2d");
  const W = cv.width = cv.offsetWidth * 2, H = cv.height = 640;
  ctx.fillStyle = "#0b0f13"; ctx.fillRect(0, 0, W, H);
  const h = (S.history.get(S.selected) || []).filter(p => now() - p.t <= S.windowMs);
  const padL = 90, padB = 60, padT = 30, padR = 20;
  ctx.strokeStyle = "#2d3a47"; ctx.fillStyle = "#8b98a5"; ctx.font = "22px sans-serif";
  for (let i = 0; i <= 4; i++) { const y = padT + (H - padT - padB) * i / 4; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke(); ctx.fillText("$" + (1 - i / 4).toFixed(2), 10, y + 7); }
  ctx.fillText("Price (Y) vs Time (X) — " + S.selected, padL, 24);
  if (h.length < 2) { ctx.fillText("Collecting data… (need ≥2 polls)", padL, H / 2); return; }
  const t0 = h[0].t, t1 = h[h.length - 1].t || now();
  const X = t => padL + (W - padL - padR) * (t - t0) / Math.max(1, t1 - t0);
  const Y = p => padT + (H - padT - padB) * (1 - p);
  ctx.strokeStyle = "#00b67a"; ctx.lineWidth = 3; ctx.beginPath();
  h.forEach((p, i) => i ? ctx.lineTo(X(p.t), Y(p.p)) : ctx.moveTo(X(p.t), Y(p.p))); ctx.stroke();
  // alert markers (>= $0.10 jumps)
  ctx.fillStyle = "#f5a623";
  for (let i = 1; i < h.length; i++) if (Math.abs(h[i].p - h[i - 1].p) >= ALERT_THRESHOLD) { ctx.beginPath(); ctx.arc(X(h[i].t), Y(h[i].p), 8, 0, 7); ctx.fill(); }
  ctx.fillStyle = "#8b98a5";
  ctx.fillText(new Date(t0).toLocaleTimeString(), padL, H - 20);
  ctx.fillText(new Date(t1).toLocaleTimeString(), W - padR - 160, H - 20);
}
function renderPortfolio() {
  const unreal = markToMarket();
  const closed = S.paper.positions.filter(p => p.status === "closed");
  const realized = closed.reduce((a, p) => a + (p.pnl || 0), 0);
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("pf-cash", fmt$(S.paper.cash)); set("pf-unreal", fmt$(unreal)); set("pf-realized", fmt$(realized));
  set("pf-equity", fmt$(S.paper.cash + S.paper.positions.filter(p => p.status === "open").reduce((a, p) => a + p.cost, 0) + unreal));
  const pt = $("positions-table");
  if (pt) pt.innerHTML = `<table><thead><tr><th>Topic</th><th>Market</th><th>Side</th><th>Contracts</th><th>Fill</th><th>Strategy</th><th>Status</th><th>PnL</th></tr></thead><tbody>` +
    (S.paper.positions.map(p => `<tr><td>${esc(p.topic)}</td><td>${esc(p.title)}</td><td>${esc(p.side)}</td><td>${p.contracts}</td><td>${fmt$(p.fill)}</td><td>${esc(p.strategy)}</td><td>${p.status}${p.result ? " (" + esc(p.result) + ")" : ""}</td><td class="${(p.pnl || 0) >= 0 ? "up" : "down"}">${p.pnl == null ? "—" : fmt$(p.pnl)}</td></tr>`).join("") || '<tr><td colspan="8" class="muted">No paper trades yet — strategies trade automatically on ≥ $0.10 alerts.</td></tr>') + `</tbody></table>`;
  // categorized performance: topic x strategy
  const cats = {};
  for (const p of closed) { const k = p.topic + " × " + p.strategy; cats[k] = cats[k] || { n: 0, pnl: 0 }; cats[k].n++; cats[k].pnl += p.pnl || 0; }
  const ct = $("category-table");
  if (ct) ct.innerHTML = `<table><thead><tr><th>Topic × Strategy</th><th>Closed trades</th><th>Realized PnL</th></tr></thead><tbody>` +
    (Object.entries(cats).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.n}</td><td class="${v.pnl >= 0 ? "up" : "down"}">${fmt$(v.pnl)}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">No closed trades yet.</td></tr>') + `</tbody></table>`;
  const cv = $("equity-chart");
  if (cv) { const ctx = cv.getContext("2d"); const W = cv.width = cv.offsetWidth * 2, H = cv.height = 400;
    ctx.fillStyle = "#0b0f13"; ctx.fillRect(0, 0, W, H);
    const eq = S.paper.equity; if (eq.length > 1) {
      const lo = Math.min(...eq.map(e => e.v), S.bankroll), hi = Math.max(...eq.map(e => e.v), S.bankroll);
      const X = i => 40 + (W - 60) * i / (eq.length - 1), Y = v => 20 + (H - 60) * (1 - (v - lo) / Math.max(1, hi - lo));
      ctx.strokeStyle = "#4c9aff"; ctx.lineWidth = 3; ctx.beginPath();
      eq.forEach((e, i) => i ? ctx.lineTo(X(i), Y(e.v)) : ctx.moveTo(X(i), Y(e.v))); ctx.stroke();
      ctx.fillStyle = "#8b98a5"; ctx.font = "20px sans-serif"; ctx.fillText("Equity curve (paper)", 40, 24);
    } else { ctx.fillStyle = "#8b98a5"; ctx.font = "22px sans-serif"; ctx.fillText("Equity curve collecting…", 40, H / 2); }
  }
}

/* ---------- Controls / init ---------- */
function init() {
  // topic pills
  const pills = $("topic-pills");
  if (pills) { pills.innerHTML = ["All", ...Object.keys(TOPICS)].map(t => `<button class="pill ${t === "All" ? "active" : ""}" data-t="${t}">${t}</button>`).join("");
    pills.querySelectorAll("button").forEach(b => b.onclick = () => { S.topicFilter = b.dataset.t; pills.querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b)); renderAll(); }); }
  // window buttons (seconds / minutes / hours)
  const wins = $("window-btns");
  if (wins) { [["60s", 60_000], ["5m", 300_000], ["1h", 3_600_000], ["24h", 86_400_000]].forEach(([label, ms], i) => {
    const b = document.createElement("button"); b.textContent = label; if (i === 2) b.classList.add("active");
    b.onclick = () => { S.windowMs = ms; wins.querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b)); renderChart(); }; wins.appendChild(b); }); }
  // strategy toggles
  const st = $("strategy-toggles");
  if (st) { st.innerHTML = Object.keys(S.strategies).map(k => `<label style="margin-right:12px"><input type="checkbox" data-s="${k}" ${S.strategies[k] ? "checked" : ""}> ${k}</label>`).join("");
    st.querySelectorAll("input").forEach(c => c.onchange = () => S.strategies[c.dataset.s] = c.checked); }
  const bank = $("bankroll-input"); if (bank) bank.onchange = () => { S.bankroll = Math.max(10, num(bank.value) || 1000); S.paper.cash = S.bankroll; };
  const modeBtn = $("mode-toggle");
  if (modeBtn) modeBtn.onclick = () => { setMode(S.mode === "live" ? "sim" : "live", "Manual toggle"); poll(); };
  const baseSel = $("base-select");
  if (baseSel) baseSel.onchange = () => { S.base = baseSel.value; S.markets.clear(); S.history.clear(); poll(); };
  const pauseBtn = $("pause-btn");
  if (pauseBtn) pauseBtn.onclick = () => { if (S.timer) { clearInterval(S.timer); S.timer = null; pauseBtn.textContent = "▶ Resume"; } else { S.timer = setInterval(poll, POLL_MS); pauseBtn.textContent = "⏸ Pause"; } };
  setMode("live", ""); poll(); S.timer = setInterval(poll, POLL_MS);
}
document.addEventListener("DOMContentLoaded", init);
