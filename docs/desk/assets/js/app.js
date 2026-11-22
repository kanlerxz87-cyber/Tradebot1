/* Dashboard runtime.
   - Loads the published snapshot (data/*.json) — always available on GitHub Pages.
   - Optionally upgrades to a live connection: same-origin WebSocket when the local server
     is running, or direct public Kalshi REST calls from the browser if the exchange allows
     cross-origin reads. Every failure path is surfaced in the UI rather than hidden.
   - Nothing is fabricated: if a value is missing it renders an em dash.
*/
(function () {
  "use strict";

  const DATA = (window.SITE_DATA_PREFIX || "data/");
  const THRESHOLD = 0.10;
  const RANGES = [
    { id: "30s", label: "30s", seconds: 30 },
    { id: "2m", label: "2m", seconds: 120 },
    { id: "15m", label: "15m", seconds: 900 },
    { id: "1h", label: "1h", seconds: 3600 },
    { id: "6h", label: "6h", seconds: 21600 },
    { id: "24h", label: "24h", seconds: 86400 },
    { id: "all", label: "All", seconds: null },
  ];

  const state = {
    latest: null,
    history: {},
    alerts: [],
    resolved: [],
    paper: null,
    topic: "all",
    market: null,
    range: localStorage.getItem("kt.range") || "1h",
    query: "",
    sort: { key: "notional_24h_est", dir: -1 },
    live: { mode: "snapshot", ok: false, note: "", timer: null, ws: null, lastPoint: {} },
    seenAlerts: new Set(),
    chatPinned: { all: true, model: true },
  };

  /* ------------------------------------------------------------ utilities */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (str) => String(str === null || str === undefined ? "" : str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const num = (v, digits) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—"
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 0 : digits }));
  const usd = (v, digits) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—"
    : "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: digits === undefined ? 2 : digits, maximumFractionDigits: digits === undefined ? 2 : digits }));
  const cents = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Math.round(Number(v) * 100) + "¢");
  const signed = (v, digits) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    return (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(digits === undefined ? 2 : digits);
  };
  const clampText = (s, n) => { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
  const timeAgo = (iso) => {
    if (!iso) return "—";
    const ts = Date.parse(iso);
    if (Number.isNaN(ts)) return "—";
    const secs = Math.max(0, Math.round((Date.now() - ts) / 1000));
    if (secs < 60) return secs + "s ago";
    if (secs < 3600) return Math.round(secs / 60) + "m ago";
    if (secs < 86400) return Math.round(secs / 3600) + "h ago";
    return Math.round(secs / 86400) + "d ago";
  };
  const clock = (iso) => {
    if (!iso) return "--:--:--";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "--:--:--";
    return d.toISOString().slice(11, 19);
  };
  const topicLabel = (id) => {
    const map = { gas: "Gas prices", elections: "Elections", culture: "Culture", crypto: "Crypto", golf: "Golf" };
    return map[id] || id || "—";
  };
  const topicChip = (id) => `<span class="chip ${esc(id)}">${esc(topicLabel(id))}</span>`;

  async function getJson(path) {
    const res = await fetch(DATA + path + "?v=" + Date.now(), { cache: "no-store" });
    if (!res.ok) throw new Error(path + " → HTTP " + res.status);
    return res.json();
  }

  /* --------------------------------------------------------------- loading */
  async function loadSnapshot() {
    const [latest, history, alerts, resolved, paper] = await Promise.allSettled([
      getJson("latest.json"),
      getJson("history.json"),
      getJson("alerts.json"),
      getJson("resolved.json"),
      getJson("paper.json"),
    ]);
    if (latest.status === "fulfilled") state.latest = latest.value;
    if (history.status === "fulfilled") state.history = history.value.series || {};
    if (alerts.status === "fulfilled") state.alerts = alerts.value.items || [];
    if (resolved.status === "fulfilled") state.resolved = resolved.value.items || [];
    if (paper.status === "fulfilled") state.paper = paper.value;

    if (!state.latest) {
      showFatal("No snapshot data found. Run `python -m kalshi_trader.cli collect` or wait for the next scheduled collection.");
      return;
    }
    const embedsBlocked = state.latest.data_env === "demo";
    if (embedsBlocked) { /* demo data still renders; banner explains the source */ }

    ensureSelection();
    renderAll();
  }

  function showFatal(message) {
    const box = $("#dataState");
    if (box) {
      box.innerHTML = `<div class="banner bad"><b>No data.</b><span class="grow">${esc(message)}</span></div>`;
    }
  }

  function allMarkets() {
    if (!state.latest || !state.latest.topics) return [];
    return Object.values(state.latest.topics).flatMap((t) => (t.markets || []).map((m) => ({ ...m, topic: m.topic || t.id })));
  }

  function allEvents() {
    if (!state.latest || !state.latest.topics) return [];
    return Object.values(state.latest.topics).flatMap((t) => (t.events || []).map((e) => ({ ...e, topic: e.topic || t.id })));
  }


  function visibleMarkets() {
    let rows = allMarkets();
    if (state.topic !== "all") rows = rows.filter((m) => m.topic === state.topic);
    if (state.query) {
      const q = state.query.toLowerCase();
      rows = rows.filter((m) =>
        (m.title || "").toLowerCase().includes(q) ||
        (m.ticker || "").toLowerCase().includes(q) ||
        (m.series_ticker || "").toLowerCase().includes(q));
    }
    const { key, dir } = state.sort;
    rows.sort((a, b) => {
      const av = a[key] === null || a[key] === undefined ? -Infinity : a[key];
      const bv = b[key] === null || b[key] === undefined ? -Infinity : b[key];
      if (typeof av === "string" || typeof bv === "string") return String(av).localeCompare(String(bv)) * dir;
      return (av - bv) * dir;
    });
    return rows;
  }

  function ensureSelection() {
    const params = new URLSearchParams(location.search);
    const urlTopic = params.get("topic");
    if (urlTopic && ["gas", "elections", "culture", "crypto", "golf"].includes(urlTopic)) state.topic = urlTopic;
    const urlMarket = params.get("market");
    const urlRange = params.get("range");
    if (urlRange && RANGES.some((r) => r.id === urlRange)) state.range = urlRange;

    const rows = visibleMarkets();
    if (urlMarket && allMarkets().some((m) => m.ticker === urlMarket)) {
      state.market = urlMarket;
      const match = allMarkets().find((m) => m.ticker === urlMarket);
      if (match && state.topic !== "all") state.topic = match.topic;
    } else if (!state.market || !rows.some((m) => m.ticker === state.market)) {
      const leader = rows.slice().sort((a, b) => (b.notional_24h_est || 0) - (a.notional_24h_est || 0))[0];
      state.market = leader ? leader.ticker : null;
    }
  }

  function selectedMarket() {
    return allMarkets().find((m) => m.ticker === state.market) || null;
  }

  /* --------------------------------------------------------------- render */
  function renderAll() {
    renderHeaderState();
    renderKpis();
    renderTabs();
    renderLeaderboard();
    renderMarkets();
    renderChartPanel();
    renderChats();
    renderResolved();
    renderPortfolioPanel();
    renderDataNotes();
  }

  function renderHeaderState() {
    const live = $("#liveState");
    if (!live) return;
    const latest = state.latest || {};
    const stale = latest.generated_at ? (Date.now() - Date.parse(latest.generated_at)) / 1000 > 1800 : true;
    const modeLabel = state.live.mode === "direct" ? "Direct Kalshi REST (browser)"
      : state.live.mode === "server" ? "Local server push"
      : "Published snapshot";
    live.innerHTML = `
      <span class="pulse ${stale ? "off" : "on"}"></span>
      <span><b>${esc(modeLabel)}</b> · data ${esc(timeAgo(latest.generated_at))} · ${num(latest.market_count)} markets · ${num((latest.alerts || []).length)} new alerts this cycle</span>
      <span class="chip ${stale ? "warn" : "ok"}">${stale ? "snapshot older than 30 min" : "fresh"}</span>
    `;
  }

  function renderKpis() {
    const host = $("#kpis");
    if (!host) return;
    const latest = state.latest || {};
    const topics = latest.topics || {};
    const totalNotional = Object.values(topics).reduce((sum, t) => sum + (t.notional_24h_est || 0), 0);
    const totalOi = Object.values(topics).reduce((sum, t) => sum + (t.open_interest || 0), 0);
    const perf = latest.performance ? latest.performance.headline : {};
    const alertsToday = state.alerts.filter((a) => Date.now() - Date.parse(a.iso || 0) < 86400000).length;
    const picks = (latest.picks || []).length;

    const tiles = [
      { label: "Tracked markets", value: num(latest.market_count), foot: `${num(latest.event_count)} open events scanned` },
      { label: "Est. 24h notional (5 topics)", value: usd(totalNotional, 0), foot: "price × 24h volume, derived" },
      { label: "Open interest (contracts)", value: num(totalOi), foot: "sum of open_interest_fp" },
      { label: "Swing alerts (24h)", value: num(alertsToday), foot: `threshold ≥ ${usd(THRESHOLD)}` },
      { label: "High-ROI picks this cycle", value: num(picks), foot: `model ${esc((latest.model || {}).version || "—")}` },
      { label: "Paper equity", value: usd(perf.equity), foot: `${signed(perf.total_pnl)} vs ${usd(perf.bankroll_start)} start`, cls: (perf.total_pnl || 0) >= 0 ? "up" : "down" },
    ];
    host.innerHTML = tiles.map((t) => `
      <div class="card">
        <span class="label">${esc(t.label)}</span>
        <span class="value ${t.cls || ""}">${t.value}</span>
        <span class="foot">${t.foot}</span>
      </div>`).join("");
  }

  function renderTabs() {
    const host = $("#topicTabs");
    if (!host) return;
    const topics = (state.latest && state.latest.topics) || {};
    const tabs = [{ id: "all", label: "All topics" }].concat(
      ["gas", "elections", "culture", "crypto", "golf"].map((id) => ({
        id,
        label: topics[id] ? topics[id].label : topicLabel(id),
        count: topics[id] ? topics[id].markets_count : 0,
      }))
    );
    host.innerHTML = tabs.map((t) => `
      <button class="btn ${state.topic === t.id ? "primary" : "ghost"}" data-topic="${esc(t.id)}">
        ${esc(t.label)}${t.count !== undefined ? ` <span class="small">(${num(t.count)})</span>` : ""}
      </button>`).join("");
    $$("#topicTabs [data-topic]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.topic = btn.dataset.topic;
        state.market = null;
        ensureSelection();
        renderAll();
      });
    });
  }

  function renderLeaderboard() {
    const host = $("#leaderboard");
    if (!host) return;
    let events = allEvents();
    if (state.topic !== "all") events = events.filter((e) => e.topic === state.topic);
    events.sort((a, b) => (b.notional_24h_est || 0) - (a.notional_24h_est || 0));
    const top = events.slice(0, 8);
    if (!top.length) {
      host.innerHTML = '<div class="empty">No open events for this filter in the current snapshot.</div>';
      return;
    }
    host.innerHTML = `
      <table>
        <thead><tr><th>Event (highest $ volume)</th><th>Topic</th><th class="num">Markets</th><th class="num">Est. 24h $</th><th>Closes</th><th>Source</th></tr></thead>
        <tbody>
        ${top.map((e) => `
          <tr>
            <td><span class="title">${esc(clampText(e.title, 80))}</span><div class="meta mono">${esc(e.event_ticker)}</div></td>
            <td>${topicChip(e.topic)}</td>
            <td class="num">${num(e.markets_count)}</td>
            <td class="num">${usd(e.notional_24h_est, 0)}</td>
            <td class="meta">${esc((e.close_time || "").replace("T", " ").replace("Z", "Z"))}</td>
            <td><a href="${esc(e.series_page_url || "#")}" target="_blank" rel="noopener">Kalshi</a></td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  }

  const COLUMNS = [
    { key: "title", label: "Market", cls: "" },
    { key: "topic", label: "Topic", cls: "" },
    { key: "price", label: "Price", cls: "num" },
    { key: "spread", label: "Bid / ask", cls: "num" },
    { key: "volume_24h", label: "24h vol", cls: "num" },
    { key: "open_interest", label: "Open interest", cls: "num" },
    { key: "top_book_contracts", label: "At best price", cls: "num" },
    { key: "notional_24h_est", label: "Est. 24h $", cls: "num" },
    { key: "close_time", label: "Closes", cls: "" },
    { key: "src", label: "Source", cls: "" },
  ];

  function renderMarkets() {
    const host = $("#marketTable");
    if (!host) return;
    const rows = visibleMarkets();
    const head = `<thead><tr>${COLUMNS.map((c) => {
      const arrow = state.sort.key === c.key ? (state.sort.dir === 1 ? " ▲" : " ▼") : "";
      return `<th class="${c.cls}" data-sort="${c.key}">${esc(c.label)}${arrow}</th>`;
    }).join("")}</tr></thead>`;
    if (!rows.length) {
      host.innerHTML = '<div class="empty">No markets match this filter in the current snapshot.</div>';
      return;
    }
    host.innerHTML = `
      <div class="table-wrap">
        <table>
          ${head}
          <tbody>
          ${rows.map((m) => `
            <tr data-ticker="${esc(m.ticker)}" class="${m.ticker === state.market ? "selected" : ""}">
              <td>
                <span class="title">${esc(clampText(m.title, 74))}</span>
                <div class="meta mono">${esc(m.ticker)}</div>
              </td>
              <td>${topicChip(m.topic)}</td>
              <td class="num">${cents(m.price)}</td>
              <td class="num">${cents(m.yes_bid)} / ${cents(m.yes_ask)}</td>
              <td class="num">${num(m.volume_24h)}</td>
              <td class="num">${num(m.open_interest)}</td>
              <td class="num">${num(m.top_book_contracts)}</td>
              <td class="num">${usd(m.notional_24h_est, 0)}</td>
              <td class="meta">${esc((m.close_time || "").slice(0, 16).replace("T", " "))}</td>
              <td><a href="${esc(m.api_url || m.series_page_url || "#")}" target="_blank" rel="noopener">API</a></td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    $$("#marketTable tbody tr").forEach((tr) => {
      tr.addEventListener("click", () => {
        state.market = tr.dataset.ticker;
        renderMarkets();
        renderChartPanel();
        const params = new URLSearchParams(location.search);
        params.set("market", state.market);
        if (state.topic !== "all") params.set("topic", state.topic); else params.delete("topic");
        history.replaceState(null, "", "?" + params.toString());
      });
    });
    $$("#marketTable th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (key === "src") return;
        state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : -1 };
        renderMarkets();
      });
    });
  }

  function renderChartPanel() {
    const host = $("#chartPanel");
    if (!host) return;
    const market = selectedMarket();
    if (!market) {
      host.innerHTML = '<div class="empty">Select a market to chart.</div>';
      return;
    }
    const points = (state.history[market.ticker] || []).slice();
    const latest = state.latest;
    if (latest && latest.generated_ts && market.price !== undefined) {
      points.push([latest.generated_ts, market.price]);
    }
    const range = RANGES.find((r) => r.id === state.range) || RANGES[3];
    const allPoints = points.slice().sort((a, b) => a[0] - b[0]);
    const lastTs = allPoints.length ? allPoints[allPoints.length - 1][0] : Math.floor(Date.now() / 1000);
    const xMin = range.seconds ? lastTs - range.seconds : (allPoints.length ? allPoints[0][0] : lastTs - 3600);
    const inWindow = allPoints.filter((p) => p[0] >= xMin);
    const tickerAlerts = state.alerts.filter((a) => a.ticker === market.ticker);

    host.innerHTML = `
      <div class="card">
        <div class="chart-toolbar">
          <div class="pills" id="rangePills">
            ${RANGES.map((r) => `<button data-range="${r.id}" class="${r.id === state.range ? "active" : ""}">${r.label}</button>`).join("")}
          </div>
          <span class="spacer" style="flex:1"></span>
          <button class="btn ghost" id="openKalshi">Open on Kalshi ↗</button>
        </div>
        <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px">
          <b style="font-size:15px">${esc(clampText(market.title, 96))}</b>
          ${topicChip(market.topic)}
          <span class="mono small">${esc(market.ticker)}</span>
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-dim);margin-bottom:8px">
          <span>Price <b>${cents(market.price)}</b></span>
          <span>YES bid ${cents(market.yes_bid)} / ask ${cents(market.yes_ask)}</span>
          <span>Spread ${market.spread === null || market.spread === undefined ? "—" : cents(market.spread)}</span>
          <span>24h volume ${num(market.volume_24h)}</span>
          <span>Open interest ${num(market.open_interest)}</span>
          <span>Closes ${esc((market.close_time || "—").slice(0, 16).replace("T", " "))}</span>
        </div>
        <div class="chart-shell" id="priceChart"></div>
        <div class="chart-note">
          X axis = time (UTC clock), Y axis = contract price in dollars. Red/green dashed lines mark recorded ≥ $0.10 swings.
          ${range.seconds && inWindow.length < 2 ? `<b>Only ${inWindow.length} point(s) in this window</b> — the snapshot is published every 15 minutes, so seconds/minutes windows fill only while the live server or direct mode is connected.` : ""}
        </div>
      </div>`;

    Charts.line($("#priceChart"), {
      points: allPoints,
      xMin,
      xMax: lastTs + Math.max(5, range.seconds ? range.seconds * 0.02 : 30),
      yMin: 0,
      yMax: 1,
      height: 320,
      markers: tickerAlerts.slice(-40).map((a) => ({ ts: a.ts, direction: a.direction })),
      emptyText: "No recorded price points for this market yet.",
    });

    $$("#rangePills [data-range]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.range = btn.dataset.range;
        localStorage.setItem("kt.range", state.range);
        renderChartPanel();
      });
    });
    const openLink = $("#openKalshi");
    if (openLink) openLink.addEventListener("click", () => {
      window.open(market.series_page_url || market.api_url || "#", "_blank", "noopener");
    });

    const depthHost = $("#depthPanel");
    if (depthHost) {
      depthHost.innerHTML = `<div class="card"><h3>Liquidity — contracts resting at each price</h3><div id="depthInner"></div>
        <div class="toolbar" style="margin-top:10px"><button class="btn ghost" id="liveBook">Fetch live orderbook</button>
        <span class="small" id="liveBookNote"></span></div></div>`;
      Charts.depth($("#depthInner"), market.orderbook || null, { depth: 6 });
      const btn = $("#liveBook");
      if (btn) btn.addEventListener("click", () => fetchLiveBook(btn));
    }
  }

  async function fetchLiveBook(btn) {
    const market = selectedMarket();
    const note = $("#liveBookNote");
    if (!market) return;
    btn.disabled = true;
    note.textContent = "requesting…";
    const base = (window.KALSHI_API_BASE || "https://external-api.kalshi.com/trade-api/v2");
    try {
      const res = await fetch(`${base}/markets/${encodeURIComponent(market.ticker)}/orderbook?depth=10`, { mode: "cors" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const payload = await res.json();
      const book = payload.orderbook_fp || payload.orderbook;
      if (!book) throw new Error("unexpected response");
      const yes = (book.yes_dollars || []).map(([p, c]) => ({ price: Number(p), contracts: Number(c) }));
      const no = (book.no_dollars || []).map(([p, c]) => ({ price: Number(p), contracts: Number(c) }));
      const yesSorted = yes.sort((a, b) => a.price - b.price);
      const noSorted = no.sort((a, b) => a.price - b.price);
      const normalized = {
        yes_bids: yesSorted.slice().reverse().slice(0, 8),
        yes_asks: noSorted.slice().reverse().map((l) => ({ price: 1 - l.price, contracts: l.contracts })).slice(0, 8),
        spread: yesSorted.length && noSorted.length ? (1 - noSorted[noSorted.length - 1].price) - yesSorted[yesSorted.length - 1].price : null,
        yes_depth_contracts: yes.reduce((s, l) => s + l.contracts, 0),
        no_depth_contracts: no.reduce((s, l) => s + l.contracts, 0),
      };
      Charts.depth($("#depthInner"), normalized, { depth: 6 });
      note.textContent = "live read at " + new Date().toISOString().slice(11, 19) + " UTC";
      state.live.mode = "direct";
      state.live.ok = true;
      renderHeaderState();
    } catch (err) {
      note.innerHTML = `<span class="warn">Live read failed (${esc(err.message)}). This is usually browser CORS policy; the published snapshot above is unaffected.</span>`;
    } finally {
      btn.disabled = false;
    }
  }

  /* ---------------------------------------------------------------- chats */
  function alertMarkup(alert, opts) {
    const dir = alert.direction === "up" ? "up" : "down";
    const model = alert.model || {};
    const why = [
      model.score !== undefined ? `model score ${Number(model.score).toFixed(2)} · est. ROI ${Number(model.roi_pct_est).toFixed(1)}%` : null,
      model.reasons ? model.reasons.join(" · ") : null,
      alert.model && alert.model.note ? `<i>${esc(alert.model.note)}</i>` : null,
    ].filter(Boolean).join("<br>");
    return `
      <div class="msg" data-alert="${esc(alert.id)}">
        <div class="ts">${clock(alert.iso)}<br><span style="font-size:9.5px">UTC</span></div>
        <div>
          <div class="head">
            ${topicChip(alert.topic)}
            <span class="dir ${dir}">${dir === "up" ? "▲" : "▼"} ${signed(alert.delta, 2)}</span>
            <span class="small">${cents(alert.from_price)} → ${cents(alert.to_price)} (${signed(alert.pct_change, 1)}%)</span>
            ${opts && opts.showScore && model.score !== undefined ? `<span class="chip ok">score ${Number(model.score).toFixed(2)}</span>` : ""}
          </div>
          <div class="title">${esc(clampText(alert.title, 110))}</div>
          <div class="links">
            <span class="mono small">${esc(alert.ticker)}</span>
            <a href="${esc(alert.api_url || "#")}" target="_blank" rel="noopener">market API</a>
            <a href="${esc(alert.series_page_url || "#")}" target="_blank" rel="noopener">Kalshi page</a>
            <button class="toggle">why?</button>
          </div>
          <div class="why">${why || "No model verdict recorded for this alert."}</div>
        </div>
      </div>`;
  }

  function renderChats() {
    const allHost = $("#chatAll");
    const modelHost = $("#chatModel");
    if (!allHost || !modelHost) return;

    const liveAlerts = state.liveAlerts || [];
    const all = liveAlerts.concat(state.alerts).sort((a, b) => (a.ts || 0) - (b.ts || 0));
    const picks = all.filter((a) => a.model && a.model.eligible === true);

    allHost.innerHTML = all.length
      ? all.slice(-120).map((a) => alertMarkup(a, {})).join("")
      : '<div class="chat-empty">No ≥ $0.10 swings recorded yet. The chat fills as cycles detect moves.</div>';
    modelHost.innerHTML = picks.length
      ? picks.slice(-80).map((a) => alertMarkup(a, { showScore: true })).join("")
      : '<div class="chat-empty">No alert has passed the model filter yet. The model requires score ≥ 0.45, est. ROI ≥ 6%, spread ≤ $0.06 and 24h volume ≥ 100 contracts.</div>';

    $$(".msg button.toggle").forEach((btn) => {
      btn.addEventListener("click", () => btn.closest(".msg").classList.toggle("open"));
    });

    ["all", "model"].forEach((key) => {
      const log = key === "all" ? allHost : modelHost;
      if (state.chatPinned[key]) log.scrollTop = log.scrollHeight;
      if (!log.dataset.bound) {
        log.dataset.bound = "1";
        log.addEventListener("scroll", () => {
          state.chatPinned[key] = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
        }, { passive: true });
      }
    });
  }

  /* ------------------------------------------------------------- resolved */
  function renderResolved() {
    const host = $("#resolvedTable");
    if (!host) return;
    const rows = (state.resolved || []).filter((r) => !state.topic || state.topic === "all" || r.topic === state.topic);
    if (!rows.length) {
      host.innerHTML = '<div class="empty">No settled markets recorded yet. Resolution tracking starts from the first cycle.</div>';
      return;
    }
    host.innerHTML = `
      <div class="table-wrap" style="max-height:340px">
        <table>
          <thead><tr><th>Market</th><th>Topic</th><th>Outcome</th><th>Closed</th><th>Source</th></tr></thead>
          <tbody>
          ${rows.slice(0, 80).map((r) => `
            <tr>
              <td><span class="title">${esc(clampText(r.title, 76))}</span><div class="meta mono">${esc(r.ticker)}</div></td>
              <td>${topicChip(r.topic)}</td>
              <td><span class="chip ${r.resolution === "YES" ? "ok" : "bad"}">${esc(r.resolution || "—")}</span></td>
              <td class="meta">${esc((r.close_time || r.settled_ts || "—").slice(0, 16).replace("T", " "))}</td>
              <td><a href="${esc(r.api_url || r.source || "#")}" target="_blank" rel="noopener">verify</a></td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  }

  /* ------------------------------------------------------------ portfolio */
  function renderPortfolioPanel() {
    const host = $("#portfolioPanel");
    if (!host) return;
    const paper = state.paper;
    if (!paper) { host.innerHTML = '<div class="empty">No paper ledger yet.</div>'; return; }
    const perf = paper.summary || (state.latest ? state.latest.performance.summary : {}) || {};
    const head = paper.headline || {};
    host.innerHTML = `
      <div class="grid kpi" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <div class="card"><span class="label">Equity</span><span class="value">${usd(head.equity)}</span><span class="foot">start ${usd(head.bankroll_start)}</span></div>
        <div class="card"><span class="label">Total P&L</span><span class="value ${(head.total_pnl || 0) >= 0 ? "up" : "down"}">${signed(head.total_pnl)}</span><span class="foot">${signed(head.roi_pct, 2)}%</span></div>
        <div class="card"><span class="label">Closed trades</span><span class="value">${num(perf.trades)}</span><span class="foot">win rate ${num(perf.win_rate_pct, 1)}%</span></div>
        <div class="card"><span class="label">Open positions</span><span class="value">${num(head.open_positions)}</span><span class="foot">cash ${usd(head.cash)}</span></div>
      </div>
      <div class="chart-note">${
        head.fee_verified ? "Fees: verified model." :
        "Fees modelled at 7% × contracts × price × (1 − price), rounded up to the cent. <b>Unverified</b> against Kalshi's current fee schedule — see Flagged for Review."
      }</div>`;
  }

  function renderDataNotes() {
    const host = $("#dataNotes");
    if (!host || !state.latest) return;
    const latest = state.latest;
    const errors = latest.errors || [];
    host.innerHTML = `
      <div class="status-line">
        <span>Source: <b>${esc(latest.data_env === "demo" ? "Kalshi demo" : "Kalshi production")}</b> ${esc(latest.rest_base || "")}</span>
        <span>·</span><span>Generated ${esc(latest.generated_at)} in ${esc(latest.cycle_seconds)}s</span>
        <span>·</span><span>${esc(latest.alerts.length)} alerts this cycle</span>
        <span>·</span><span>Exchange ${latest.exchange && latest.exchange.trading_active ? "trading" : "status unknown"}</span>
      </div>
      ${errors.length ? `<div class="banner warn" style="margin-top:10px"><b>${errors.length} collection warning(s):</b><span class="grow">${errors.map((e) => esc(e)).join(" · ")}</span></div>` : ""}
      <div class="banner" style="margin-top:10px">
        <span class="grow"><b>Snapshot cadence.</b> The public site is refreshed by a GitHub Actions cron job (15 minutes). The two chats, the chart and the orderbook also support a live upgrade: run <code>python -m kalshi_trader.cli serve</code> for WebSocket pushes, or press “Fetch live orderbook” to test direct browser access.</span>
      </div>`;
  }

  /* ------------------------------------------------------------ live mode */
  async function probeDirect() {
    const base = window.KALSHI_API_BASE || "https://external-api.kalshi.com/trade-api/v2";
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(base + "/exchange/status", { mode: "cors", signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) throw new Error("HTTP " + res.status);
      await res.json();
      state.live.mode = "direct";
      state.live.ok = true;
      state.live.note = "Direct browser access to the public Kalshi API works.";
    } catch (err) {
      state.live.mode = "snapshot";
      state.live.ok = false;
      state.live.note = "Direct browser access to Kalshi is blocked (CORS or offline). Snapshot mode stays on; the local server proxy is the alternative.";
    }
    renderHeaderState();
    const host = $("#liveNotice");
    if (host) {
      host.innerHTML = `<div class="banner ${state.live.ok ? "ok" : ""}">
        <span class="grow"><b>Live upgrade test:</b> ${esc(state.live.note)}</span>
        ${state.live.ok ? `<button class="btn" id="startLive">Poll selected market live</button>` : `<a class="btn ghost" href="strategies.html#live">How to run the live server</a>`}
      </div>`;
      const btn = $("#startLive");
      if (btn) btn.addEventListener("click", startLivePolling);
    }
  }

  async function probeServer() {
    try {
      const res = await fetch("api/status", { cache: "no-store" });
      if (!res.ok) return false;
      const status = await res.json();
      state.live.mode = "server";
      state.live.ok = true;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${location.host}/ws`);
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === "tick" && msg.payload) {
            state.latest = msg.payload;
            ingestLivePayload(msg.payload);
          }
        } catch (err) { /* ignore malformed frame */ }
      };
      ws.onclose = () => { state.live.ws = null; };
      state.live.ws = ws;
      const host = $("#liveNotice");
      if (host) {
        host.innerHTML = `<div class="banner ok"><span class="grow"><b>Local server connected.</b> Receiving pushes every ${esc(status.interval_seconds)}s · cycles completed ${esc(status.cycles_completed)}.</span></div>`;
      }
      renderHeaderState();
      return true;
    } catch (err) {
      return false;
    }
  }

  function ingestLivePayload(payload) {
    // Merge a fresh server push into the dashboard state without a full reload.
    const markets = Object.values(payload.topics || {}).flatMap((t) => (t.markets || []).map((m) => ({ ...m, topic: m.topic || t.id })));
    const prev = state.live.lastPrices || {};
    const fresh = [];
    markets.forEach((m) => {
      const before = prev[m.ticker];
      if (before !== undefined && Math.abs((m.price || 0) - before) >= THRESHOLD) {
        fresh.push({
          id: "live-" + m.ticker + "-" + (payload.generated_ts || Date.now()),
          ts: payload.generated_ts || Math.floor(Date.now() / 1000),
          iso: payload.generated_at,
          ticker: m.ticker,
          topic: m.topic,
          title: m.title,
          direction: m.price > before ? "up" : "down",
          from_price: before,
          to_price: m.price,
          delta: m.price - before,
          abs_delta: Math.abs(m.price - before),
          pct_change: before ? ((m.price - before) / before) * 100 : null,
          api_url: m.api_url,
          series_page_url: m.series_page_url,
        });
      }
      prev[m.ticker] = m.price;
      if (m.ticker && m.price !== undefined) {
        const series = state.history[m.ticker] || (state.history[m.ticker] = []);
        series.push([payload.generated_ts || Math.floor(Date.now() / 1000), m.price]);
      }
    });
    state.live.lastPrices = prev;
    state.liveAlerts = fresh.concat(state.liveAlerts || []).slice(0, 200);
    renderAll();
  }

  function startLivePolling() {
    const market = selectedMarket();
    if (!market || !market.series_ticker) return;
    if (state.live.timer) clearInterval(state.live.timer);
    const base = window.KALSHI_API_BASE || "https://external-api.kalshi.com/trade-api/v2";
    const btn = $("#startLive");
    if (btn) btn.textContent = "Live polling active (15s)";
    const poll = async () => {
      try {
        const res = await fetch(`${base}/markets?series_ticker=${encodeURIComponent(market.series_ticker)}&status=open&limit=200`, { mode: "cors" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const payload = await res.json();
        const found = (payload.markets || []).find((m) => m.ticker === market.ticker);
        if (!found) return;
        const price = found.yes_bid_dollars !== undefined && found.yes_ask_dollars !== undefined
          ? (Number(found.yes_bid_dollars) + Number(found.yes_ask_dollars)) / 2
          : Number(found.last_price_dollars || 0);
        const ts = Math.floor(Date.now() / 1000);
        const series = state.history[market.ticker] || (state.history[market.ticker] = []);
        const prev = series.length ? series[series.length - 1][1] : null;
        series.push([ts, price]);
        if (prev !== null && Math.abs(price - prev) >= THRESHOLD - 1e-9) {
          const alert = {
            id: "direct-" + market.ticker + "-" + ts,
            ts, iso: new Date().toISOString(),
            ticker: market.ticker, topic: market.topic, title: market.title,
            direction: price > prev ? "up" : "down",
            from_price: prev, to_price: price, delta: price - prev, abs_delta: Math.abs(price - prev),
            pct_change: prev ? ((price - prev) / prev) * 100 : null,
            api_url: market.api_url, series_page_url: market.series_page_url,
          };
          state.liveAlerts = [alert].concat(state.liveAlerts || []).slice(0, 200);
        }
        renderChartPanel();
        renderChats();
      } catch (err) {
        const note = $("#liveBookNote");
        if (note) note.innerHTML = `<span class="warn">Live poll failed: ${esc(err.message)}</span>`;
      }
    };
    poll();
    state.live.timer = setInterval(poll, 15000);
  }

  /* ----------------------------------------------------------------- init */
  function wireControls() {
    const search = $("#search");
    if (search) search.addEventListener("input", () => { state.query = search.value.trim(); renderMarkets(); });
    const refresh = $("#refresh");
    if (refresh) refresh.addEventListener("click", () => loadSnapshot());
    const probe = $("#testLive");
    if (probe) probe.addEventListener("click", probeDirect);
  }

  async function init() {
    wireControls();
    await loadSnapshot();
    const onServer = await probeServer();
    if (!onServer) probeDirect();
    setInterval(async () => {
      try {
        const latest = await getJson("latest.json");
        if (!state.latest || latest.generated_ts !== state.latest.generated_ts) {
          state.latest = latest;
          const history = await getJson("history.json");
          state.history = history.series || state.history;
          const alerts = await getJson("alerts.json");
          state.alerts = alerts.items || state.alerts;
          const resolved = await getJson("resolved.json");
          state.resolved = resolved.items || state.resolved;
          const paper = await getJson("paper.json");
          state.paper = paper;
          ensureSelection();
          renderAll();
        } else {
          renderHeaderState();
        }
      } catch (err) { /* keep the last good snapshot */ }
    }, 60000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
