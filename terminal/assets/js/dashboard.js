/* dashboard.js — the live surface.
 *
 * Data path: this browser → GET /events?status=open&with_nested_markets=true on the
 * demo root (public, no key). Every row is normalised by Desk.buildRow, which drops
 * anything outside the five topics and anything with no price.
 *
 * Two alert sources are shown together and labelled separately:
 *   SERVER  — terminal/data/alerts.json, written by tools/terminal-collect.mjs on a
 *             schedule from a host that can reach Kalshi. Survives refreshes and is
 *             the same for every visitor.
 *   SESSION — swings this tab has observed while open (AlertEngine).
 *
 * Charts: candlesticks (1-minute candles, official schema) are backfilled for the
 * selected contract and window, then live poll points are layered on top.
 */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    simulated: false,
    paused: false,
    topic: 'all',
    rows: [],
    events: [],
    byTicker: new Map(),
    selectedTicker: null,
    pollMs: 4000,
    backoffUntil: 0,
    engine: new AlertEngine(90000),
    chart: null,
    logged: [],            // server-observed alerts (terminal/data/alerts.json)
    sessionAlerts: [],     // alerts this tab produced
    sound: false,
    rand: SimulatedFeed.rng(20261122),
    lastRefresh: null,
    candle: { ticker: null, rangeSec: null, interval: null, points: [], error: null },
    lastAlertSignature: '',
  };

  const DEFAULT_POLL = 4000;
  const BACKOFF_POLL = 15000;

  /* ---------------- helpers ---------------- */
  const topicShort = (id) => (TOPIC_BY_ID[id] || {}).short || '?';
  const topicBadge = (id) => `<span class="badge topic-${escapeHtml(id)}">${escapeHtml(topicShort(id))}</span>`;
  const pct = (p) => (p == null ? '—' : Math.round(p * 100) + '¢');
  const truncate = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

  function setBadge(mode, text) {
    const el = $('#connectionBadge');
    if (!el) return;
    el.className = 'badge ' + (mode === 'live' ? 'live' : mode === 'sim' ? 'sim' : mode === 'error' ? 'err' : 'info');
    el.textContent = text;
  }

  function topicRows() {
    return state.rows.filter((r) => state.topic === 'all' || r.topic === state.topic);
  }

  /* ---------------- data loading ---------------- */
  function rowFromMarket(market, event) {
    const row = Desk.buildRow(event || { event_ticker: market.event_ticker, title: market.title }, market);
    if (!row) return null;
    row.modelScore = 0; // filled by rankAndScore
    return row;
  }

  async function fetchLiveRows() {
    const res = await Kalshi.getEvents({ status: 'open', limit: 200 });
    if (!res.ok) {
      const err = new Error('Kalshi demo API request failed (HTTP ' + (res.status || 'network/CORS') + (res.error ? ': ' + res.error : '') + ')');
      err.status = res.status || 0;
      throw err;
    }
    const flat = await Kalshi.flattenEvents(res);
    const rows = [];
    const seen = new Set();
    for (const { event, market } of flat) {
      const row = rowFromMarket(market, event);
      if (!row || seen.has(row.ticker)) continue;
      seen.add(row.ticker);
      rows.push(row);
    }
    state.events = Kalshi.num(0) === 0 ? Desk.groupEvents(rows) : [];
    return rows;
  }

  function simulatedRows() {
    return SimulatedFeed.makeSnapshot(Math.floor(Date.now() / 60000))
      .map(({ event, market }) => {
        const row = rowFromMarket(market, event);
        if (row) row.sim = true;
        return row;
      })
      .filter(Boolean);
  }

  function simulateTick() {
    for (const r of state.rows) {
      const newLast = SimulatedFeed.stepPrice(r.price ?? 0.5, state.rand);
      r.previousPrice = r.price;
      r.dayChange = r.previousPrice != null ? Number((newLast - r.previousPrice).toFixed(4)) : null;
      r.price = newLast;
      r.yesBid = Math.max(0.01, newLast - 0.01);
      r.yesAsk = Math.min(0.99, newLast + 0.01);
      r.volume = (r.volume || 0) + Math.round(state.rand() * 40);
      r.notional24h = r.volume24h != null ? Number((r.volume24h * newLast).toFixed(2)) : null;
      r.spread = 0.02;
    }
  }

  /* Rank by the volume proxy the rows actually carry, so the model's "liquidity"
     input is computed from something and not a constant. */
  function rankAndScore(rows) {
    const sorted = [...rows].sort((a, b) => (b.notional24h || 0) - (a.notional24h || 0));
    const n = Math.max(1, rows.length - 1);
    sorted.forEach((r, i) => {
      r.volRank = i / n;
      r.modelScore = Model.score(null, {
        volRank: r.volRank,
        spread: r.spread ?? 0.1,
        moveAbs: r.dayChange != null ? r.dayChange : 0,
        price: r.price ?? 0.5,
        openInterest: r.openInterest,
      });
    });
  }

  async function loadLoggedAlerts() {
    try {
      const res = await fetch('data/alerts.json', { cache: 'no-store' });
      if (!res.ok) { state.logged = []; return; }
      const doc = await res.json();
      state.logged = (doc.alerts || []).map(normaliseLoggedAlert).filter(Boolean);
      const meta = doc.generated_at ? ` · server log ${fmtTime(Date.parse(doc.generated_at))}` : '';
      const el = $('#refreshInfo');
      if (el && !state.simulated) el.dataset.logged = meta;
    } catch {
      state.logged = [];
    }
  }

  async function refresh() {
    if (state.paused) return;
    try {
      if (state.simulated) {
        simulateTick();
        rankAndScore(state.rows);
        state.events = Desk.groupEvents(state.rows);
        afterData();
        return;
      }
      const rows = await fetchLiveRows();
      if (Date.now() < state.backoffUntil) return; // cooling off after 429
      state.rows = rows;
      state.byTicker = new Map(rows.map((r) => [r.ticker, r]));
      rankAndScore(state.rows);
      setBadge('live', 'LIVE — demo API');
      state.pollMs = DEFAULT_POLL;
      state.lastRefresh = new Date();
      afterData();
    } catch (err) {
      console.warn('refresh failed', err);
      if (err.status === 429) {
        state.backoffUntil = Date.now() + 30000;
        state.pollMs = BACKOFF_POLL;
        setBadge('error', 'RATE LIMITED — backing off');
        return;
      }
      setBadge('error', 'DISCONNECTED');
      const box = $('#liveError');
      if (box) box.style.display = 'block';
      const txt = $('#liveErrorText');
      if (txt) txt.textContent = String(err.message || err) + ' — likely causes: this browser cannot reach the demo host (network/CORS), or you are offline. You can load the clearly-labelled simulated feed instead.';
    } finally {
      scheduleNext();
    }
  }

  function scheduleNext() {
    clearTimeout(state.timer);
    state.timer = setTimeout(refresh, state.pollMs);
  }

  /* ---------------- rendering ---------------- */
  function renderTopicChips() {
    const counts = { all: state.rows.length };
    for (const t of TOPICS) counts[t.id] = state.rows.filter((r) => r.topic === t.id).length;
    const el = $('#topicChips');
    if (!el) return;
    el.innerHTML = [['all', 'All topics'], ...TOPICS.map((t) => [t.id, t.short])]
      .map(([id, label]) => `<button class="chip ${state.topic === id ? 'active' : ''}" data-topic="${id}" role="tab" aria-selected="${state.topic === id}">${label}<span class="count">${counts[id] ?? 0}</span></button>`)
      .join('');
  }

  function renderMovers() {
    const tbody = $('#moversBody');
    if (!tbody) return;
    const movers = Desk.dayMovers(topicRows(), { threshold: 0.10, limit: 12 });
    const count = $('#moverCount');
    if (count) count.textContent = String(movers.length);
    if (!movers.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="9">No contract in the five topics has a published one-day change of $0.10 or more right now. That is a quiet measurement, not a missing one — the exchange simply reports no such gap.</td></tr>';
      return;
    }
    tbody.innerHTML = movers.map((r) => `
      <tr data-ticker="${escapeHtml(r.ticker)}">
        <td>${topicBadge(r.topic)}</td>
        <td style="max-width:320px" title="${escapeHtml(r.title)}">${escapeHtml(truncate(r.contractTitle, 74))}<div class="muted small">${escapeHtml(r.ticker)}</div></td>
        <td class="num">${pct(r.previousPrice)}</td>
        <td class="num">${pct(r.price)}</td>
        <td class="num ${r.dayChange >= 0 ? 'up' : 'down'}">${fmtSignedUsd(r.dayChange)}</td>
        <td class="num">${fmtContracts(r.volume24h)}</td>
        <td class="num">${fmtContracts(r.openInterest)}</td>
        <td class="small">${r.sourceUrl ? `<a href="${escapeHtml(r.sourceUrl)}" target="_blank" rel="noopener noreferrer">API ↗</a>` : '—'}</td>
        <td><button class="btn small ghost" data-chart="${escapeHtml(r.ticker)}">Chart</button></td>
      </tr>`).join('');
    bindRowClicks(tbody);
  }

  function renderTable() {
    const rows = [...topicRows()].sort((a, b) => (b.notional24h || 0) - (a.notional24h || 0));
    const mc = $('#marketCount');
    if (mc) mc.textContent = String(rows.length);
    const tbody = $('#marketsBody');
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="10">No markets in this topic right now. (The demo environment recycles contracts constantly.)</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr data-ticker="${escapeHtml(r.ticker)}" class="${r.ticker === state.selectedTicker ? 'selected' : ''}">
        <td>${topicBadge(r.topic)}</td>
        <td style="max-width:340px" title="${escapeHtml(r.title)}">${escapeHtml(truncate(r.title, 88))}<div class="muted small">${escapeHtml(r.ticker)} · matched on ${escapeHtml(r.topicEvidence)}</div></td>
        <td class="num">${pct(r.price)}</td>
        <td class="num ${r.dayChange == null ? '' : r.dayChange >= 0 ? 'up' : 'down'}">${r.dayChange == null ? '—' : fmtSignedUsd(r.dayChange)}</td>
        <td class="num">${fmtContracts(r.volume24h)}</td>
        <td class="num">${r.notional24h == null ? '—' : fmtUsd(r.notional24h, 0)}</td>
        <td class="num">${r.spread == null ? '—' : pct(r.spread)}</td>
        <td class="num">${r.price > 0 ? '+' + ((1 - r.price) / r.price * 100).toFixed(0) + '%' : '—'}</td>
        <td class="num"><span class="${r.modelScore >= 65 ? 'up' : 'muted'}">${r.modelScore}</span></td>
        <td>${r.sim ? '<span class="badge sim">SIM</span>' : r.sourceUrl ? `<a href="${escapeHtml(r.sourceUrl)}" target="_blank" rel="noopener noreferrer" aria-label="API source">↗</a>` : ''}</td>
      </tr>`).join('');
    bindRowClicks(tbody);
  }

  function bindRowClicks(scope) {
    scope.querySelectorAll('tr[data-ticker]').forEach((tr) => tr.addEventListener('click', (e) => {
      if (e.target.closest('a')) return;
      selectMarket(tr.dataset.ticker);
    }));
    scope.querySelectorAll('[data-chart]').forEach((b) => b.addEventListener('click', (e) => {
      e.stopPropagation();
      selectMarket(b.dataset.chart);
    }));
  }

  /* Events grouped by topic, each topic's events ranked by estimated 24h turnover. */
  function renderTopicLeaders() {
    const wrap = $('#topicLeaders');
    if (!wrap) return;
    const events = Desk.groupEvents(topicRows());
    const ec = $('#eventCount');
    if (ec) ec.textContent = String(events.length);
    const byTopic = {};
    for (const ev of events) (byTopic[ev.topic] = byTopic[ev.topic] || []).push(ev);
    const order = state.topic === 'all' ? TOPICS.map((t) => t.id) : [state.topic];
    wrap.innerHTML = order.filter((id) => byTopic[id] && byTopic[id].length).map((id) => {
      const t = TOPIC_BY_ID[id];
      const top = byTopic[id].sort((a, b) => b.notional24hEst - a.notional24hEst).slice(0, 5);
      return `
        <div style="margin-bottom:14px">
          <h3 style="margin:8px 0 4px">${topicBadge(id)} ${escapeHtml(t ? t.name : id)} <span class="muted small">${byTopic[id].length} events</span></h3>
          <div class="table-wrap">
            <table aria-label="${escapeHtml(t ? t.name : id)} events">
              <thead><tr><th>Event</th><th class="num">Markets</th><th class="num">24h $ (est.)</th><th class="num">Open int.</th><th>Closes</th><th>Source</th></tr></thead>
              <tbody>${top.map((ev) => `
                <tr>
                  <td style="max-width:360px" title="${escapeHtml(ev.title)}">${escapeHtml(truncate(ev.title, 78))}<div class="muted small">${escapeHtml(ev.eventTicker || '')}</div></td>
                  <td class="num">${ev.marketCount}</td>
                  <td class="num">${fmtUsd(ev.notional24hEst, 0)}</td>
                  <td class="num">${fmtContracts(ev.openInterest)}</td>
                  <td class="small">${ev.closeTime ? escapeHtml(ev.closeTime.slice(0, 16).replace('T', ' ')) : '—'}</td>
                  <td class="small">${ev.exchangeUrl ? `<a href="${escapeHtml(ev.exchangeUrl)}" target="_blank" rel="noopener noreferrer">Kalshi ↗</a>` : '—'}</td>
                </tr>`).join('')}</tbody>
            </table>
          </div>
        </div>`;
    }).join('') || '<p class="muted small">No events in this topic right now.</p>';
  }

  function renderKPIs() {
    const r = state.byTicker.get(state.selectedTicker);
    if (!r) return;
    const el = (id) => document.getElementById(id);
    const set = (id, text, cls) => { const n = el(id); if (!n) return; n.textContent = text; if (cls) n.className = 'v ' + cls; };
    const st = el('selTicker'); if (st) st.textContent = r.ticker + (r.sim ? ' · SIMULATED' : '');
    const ti = el('selTitle'); if (ti) ti.textContent = r.title;
    set('kBid', pct(r.yesBid));
    set('kAsk', pct(r.yesAsk));
    set('kLast', pct(r.price));
    const dc = r.dayChange;
    set('kMove', dc == null ? '—' : fmtSignedUsd(dc), dc == null ? 'flat' : dc >= 0 ? 'up' : 'down');
    set('k24h', fmtContracts(r.volume24h));
    set('kOI', fmtContracts(r.openInterest));
    set('kSpread', r.spread == null ? '—' : pct(r.spread));
    set('kNotional', r.notional24h == null ? '—' : fmtUsd(r.notional24h, 0));
    set('kRoi', r.price > 0 ? '+' + ((1 - r.price) / r.price * 100).toFixed(1) + '% if YES' : '—');
    const v = Model.verdict(r.modelScore);
    set('kModel', `${r.modelScore} — ${v.label}`, v.cls);
    const pn = el('panelNote'); if (pn) pn.textContent = Desk.panelNote(r);
    /* The sparkline keeps its own points; add the current observation once per poll. */
    if (r.price != null) state.chart.addPoint(Date.now(), r.price);
  }

  /* ---------------- chart ---------------- */
  function chartRangeSec() {
    const active = document.querySelector('.range-btn.active');
    return active ? parseInt(active.dataset.sec, 10) : 300;
  }

  async function backfillChart() {
    const r = state.byTicker.get(state.selectedTicker);
    const info = $('#candleInfo');
    const basis = $('#chartBasis');
    if (!r || r.sim) {
      state.candle = { ticker: null, rangeSec: null, interval: null, points: [], error: null };
      if (info) info.textContent = r && r.sim ? 'Simulated market: chart shows this tab’s own points only.' : '';
      if (basis) basis.textContent = 'Simulated market — no exchange history exists for it.';
      return;
    }
    if (!r.seriesTicker) {
      if (basis) basis.textContent = 'This market does not publish a series ticker, so candlestick history cannot be requested. Only points observed in this tab are shown.';
      return;
    }
    const rangeSec = chartRangeSec();
    if (state.candle.ticker === r.ticker && state.candle.rangeSec === rangeSec) return;
    state.candle = { ticker: r.ticker, rangeSec, interval: null, points: [], error: null };
    if (info) info.textContent = 'Loading candle history…';
    const res = await Kalshi.backfill({ seriesTicker: r.seriesTicker, ticker: r.ticker, rangeSec });
    if (state.candle.ticker !== r.ticker || state.candle.rangeSec !== rangeSec) return; // selection moved on
    if (!res.ok) {
      state.candle.error = res.error || ('HTTP ' + res.status);
      if (info) info.textContent = 'Candle history unavailable (' + state.candle.error + '). The chart shows this tab’s own observations.';
      if (basis) basis.textContent = '';
      return;
    }
    state.candle = { ticker: r.ticker, rangeSec, interval: res.interval, points: res.points, error: null };
    const n = res.points.length;
    if (info) info.textContent = `${n} candle${n === 1 ? '' : 's'} · ${res.interval === 1 ? '1-minute' : res.interval === 60 ? '1-hour' : '1-day'} period · official candlestick endpoint`;
    if (basis) {
      const trades = res.points.filter((p) => p.basis === 'last_trade').length;
      basis.textContent = n
        ? `${trades} of ${n} periods had a trade (plotted as the traded price); the rest are plotted at the quoted bid/ask midpoint, which is a quote, not a trade. Live observations from this tab are layered on top every ${state.pollMs / 1000}s.`
        : 'The exchange returned no candles for this window. The chart therefore shows only observations made by this tab.';
    }
    repaintChart();
  }

  function repaintChart() {
    if (!state.chart) return;
    const live = state.chart.points.slice();
    const merged = Desk.mergeSeries(state.candle.points || [], live);
    state.chart.setPoints(merged, { rangeSec: chartRangeSec(), interval: state.candle.interval });
  }

  /* ---------------- order book ---------------- */
  async function renderBook() {
    const r = state.byTicker.get(state.selectedTicker);
    const note = $('#bookNote');
    const bidsEl = $('#bidsLadder');
    const asksEl = $('#asksLadder');
    if (!r || !bidsEl || !asksEl) return;
    let book = null;
    if (r.sim) {
      book = Kalshi.normalizeBook(SimulatedFeed.syntheticOrderbook(r.price ?? 0.5, (r.ticker.length * 2654435761) >>> 0));
    } else {
      const res = await Kalshi.getOrderbook(r.ticker);
      if (res.ok) book = Kalshi.normalizeBook(res.data);
    }
    const s = Desk.bookSummary(book, 8);
    if (!s) { if (note) note.textContent = 'Order book unavailable right now (the request failed or returned nothing).'; return; }
    const maxQty = Math.max(1, ...s.bidLadder.map((l) => l.contracts), ...s.askLadder.map((l) => l.contracts));
    const ladderHtml = (ladder, cls, empty) => ladder.length ? ladder.map((l) => `
      <div class="ladder-row ${cls}">
        <span>${pct(l.price)}</span>
        <div class="bar" style="width:${Math.min(100, (l.contracts / maxQty) * 100)}%"></div>
        <span style="text-align:right">${fmtContracts(l.contracts)} <span class="muted">· ${fmtUsd(l.dollars, 0)} → ${fmtContracts(l.cumContracts)} · ${fmtUsd(l.cumDollars, 0)}</span></span>
      </div>`).join('') : `<div class="ladder-row"><span class="muted">${empty}</span></div>`;
    bidsEl.innerHTML = ladderHtml(s.bidLadder, 'bid', 'No YES bids resting.');
    asksEl.innerHTML = ladderHtml(s.askLadder, 'ask', 'No NO bids resting, so no YES offers are implied.');
    if (note) {
      note.innerHTML = `Top 8 levels: <strong>YES bids</strong> ${fmtContracts(s.bidContracts)} contracts for <strong>${fmtUsd(s.bidDollars, 0)}</strong> total · ` +
        `<strong>YES offers</strong> (derived from NO bids) ${fmtContracts(s.askContracts)} contracts for <strong>${fmtUsd(s.askDollars, 0)}</strong>. ` +
        `${s.bestBid != null && s.bestAsk != null ? `Best bid ${pct(s.bestBid)} / best offer ${pct(s.bestAsk)} (spread ${pct(Number((s.bestAsk - s.bestBid).toFixed(4)))}). ` : ''}` +
        `${r.sim ? '<span class="badge sim">SIMULATED</span>' : `Source: <a href="${escapeHtml((SITE.demoRest) + '/markets/' + encodeURIComponent(r.ticker) + '/orderbook')}" target="_blank" rel="noopener noreferrer">GET /markets/{ticker}/orderbook ↗</a>`}`;
    }
  }

  /* ---------------- feeds ---------------- */
  const alertSeverity = (a) => Math.abs(a.abs_delta ?? a.delta ?? 0);

  function feedItems() {
    const logged = state.logged.filter((a) => (state.topic === 'all' || a.topic === state.topic));
    const session = state.sessionAlerts.filter((a) => (state.topic === 'all' || a.topic === state.topic));
    return [...logged, ...session].sort((a, b) => b.ts - a.ts).slice(0, 120);
  }

  function renderFeeds() {
    const all = $('#feedAll');
    const model = $('#feedModel');
    if (!all || !model) return;
    const items = feedItems();
    const mk = (a) => {
      const score = a.score ?? (state.byTicker.get(a.ticker) || {}).modelScore ?? null;
      const source = a.logged ? '<span class="badge ok">SERVER</span>' : '<span class="badge info">SESSION</span>';
      const delta = a.delta != null ? a.delta : (a.direction === 'down' ? -alertSeverity(a) : alertSeverity(a));
      return `
      <div class="chat-msg ${a.direction}" data-ticker="${escapeHtml(a.ticker)}" role="log">
        <div class="meta"><span>${source} ${escapeHtml(topicShort(a.topic))} · ${escapeHtml(fmtTime(a.ts))}</span><span>${score == null ? 'MODEL —' : 'MODEL ' + score}</span></div>
        <div><span class="ticker">${escapeHtml(a.ticker)}</span> <strong class="${a.direction === 'up' ? 'up' : 'down'}">${a.direction === 'up' ? '▲' : '▼'} ${fmtSignedUsd(delta)}</strong> → $${Number(a.price ?? a.to_price ?? 0).toFixed(2)}${a.from_price != null ? ` <span class="muted small">(from $${Number(a.from_price).toFixed(2)})</span>` : ''}</div>
        <div class="muted" style="margin-top:2px">${escapeHtml(truncate(a.title, 110))}</div>
        ${a.source_url ? `<div class="small"><a href="${escapeHtml(a.source_url)}" target="_blank" rel="noopener noreferrer">source ↗</a></div>` : ''}
      </div>`;
    };
    all.innerHTML = items.length ? items.map(mk).join('') : '<div class="muted small" style="padding:12px">No ≥ $0.10 swings yet. A SERVER alert appears as soon as the scheduled collector measures one; a SESSION alert appears when this tab observes the same contract at two prices $0.10 apart.</div>';
    const modelItems = items.filter((a) => {
      const score = a.score ?? (state.byTicker.get(a.ticker) || {}).modelScore ?? 0;
      return score >= Model.MODEL_FEED_THRESHOLD;
    });
    model.innerHTML = modelItems.length ? modelItems.map(mk).join('') : '<div class="muted small" style="padding:12px">No model-approved swings right now. The screen needs a scored market (liquid, tight spread, decisive move) behind the alert; see the rubric below.</div>';
    const c1 = $('#feedAllCount'); if (c1) c1.textContent = String(items.length);
    const c2 = $('#feedModelCount'); if (c2) c2.textContent = String(modelItems.length);
    [all, model].forEach((el) => el.querySelectorAll('.chat-msg[data-ticker]').forEach((m) => m.addEventListener('click', () => selectMarket(m.dataset.ticker))));
  }

  function pushAlert(a) {
    const row = state.byTicker.get(a.ticker);
    a.score = a.score ?? (row ? row.modelScore : null);
    state.sessionAlerts.push(a);
    if (state.sessionAlerts.length > 300) state.sessionAlerts = state.sessionAlerts.slice(-300);
    renderFeeds();
    if (a.ticker === state.selectedTicker) {
      showMoveBanner(a);
      renderDrivers(a);
    }
    if (state.sound) beep(a.direction);
  }

  function showMoveBanner(a) {
    const el = $('#moveBanner');
    if (!el) return;
    el.style.display = 'block';
    el.innerHTML = `<strong>${a.direction === 'up' ? '▲ SWING UP' : '▼ SWING DOWN'} ${fmtSignedUsd(a.delta)}</strong> on <code>${escapeHtml(a.ticker)}</code> → $${Number(a.price).toFixed(2)} (${a.move === 'session' ? 'vs the reference when this tab started watching' : 'within the last 2 minutes'}). Possible drivers below — links to check, not proven causation.`;
  }

  function renderDrivers(a) {
    const el = $('#driversRow');
    const wrap = $('#driversWrap');
    if (!el || !wrap) return;
    const links = driverLinks(a.topic, a.title);
    el.innerHTML = links.map((l) => `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.label)} ↗</a>`).join('');
    wrap.style.display = 'block';
  }

  function beep(direction) {
    try {
      const ctx = beep._ctx || (beep._ctx = new (window.AudioContext || window.webkitAudioContext)());
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine';
      o.frequency.value = direction === 'up' ? 880 : 330;
      g.gain.setValueAtTime(0.001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.5);
      o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + 0.55);
    } catch { /* audio unavailable */ }
  }

  function runAlertScan() {
    if (state.simulated) return;
    for (const r of state.rows) {
      if (r.price == null) continue;
      const a = state.engine.update(r.ticker, r.price, {
        ticker: r.ticker, title: r.title, topic: r.topic, stale: r.stale,
      });
      if (a) { a.score = r.modelScore; a.source_url = r.sourceUrl; pushAlert(a); }
    }
  }

  function afterData() {
    renderTopicChips();
    renderMovers();
    renderTable();
    renderTopicLeaders();
    if (!state.selectedTicker || !state.byTicker.has(state.selectedTicker)) {
      const first = [...topicRows()].sort((a, b) => (b.notional24h || 0) - (a.notional24h || 0))[0];
      if (first) state.selectedTicker = first.ticker;
    }
    renderKPIs();
    backfillChart();
    renderBook();
    runAlertScan();
    renderFeeds();
    const info = $('#refreshInfo');
    if (info) {
      info.textContent = `Tracking ${state.rows.length} contracts in 5 topics · refreshed ${fmtTime(Date.now())}` + (state.simulated ? ' · SIMULATED' : '');
    }
    /* Reload the committed server log once a minute so a new collection shows up
       without a page reload. */
    const now = Date.now();
    if (!state.lastLoggedLoad || now - state.lastLoggedLoad > 60000) {
      state.lastLoggedLoad = now;
      loadLoggedAlerts().then(renderFeeds);
    }
  }

  function selectMarket(ticker) {
    if (!state.byTicker.has(ticker)) {
      /* A server alert can name a market that is not in the current page of
         results. Do not pretend to have its data: point at the source instead. */
      toast('That contract is not in the current result page. Open its source link to view it on Kalshi.', 4000);
      return;
    }
    state.selectedTicker = ticker;
    state.chart.clear();
    renderTable();
    renderKPIs();
    repaintChart();
    backfillChart();
    renderBook();
    renderFeeds();
  }

  /* ---------------- boot ---------------- */
  async function start(simulated) {
    state.simulated = !!simulated;
    state.engine = new AlertEngine(90000);
    state.rows = simulated ? simulatedRows() : [];
    state.byTicker = new Map(state.rows.map((r) => [r.ticker, r]));
    if (simulated) {
      rankAndScore(state.rows);
      state.events = Desk.groupEvents(state.rows);
      setBadge('sim', 'SIMULATED FEED');
      const le = $('#liveError'); if (le) le.style.display = 'none';
      const sb = $('#simBanner'); if (sb) sb.style.display = 'block';
      state.lastRefresh = new Date();
      afterData();
      scheduleNext();
      return;
    }
    const sb = $('#simBanner'); if (sb) sb.style.display = 'none';
    setBadge('info', 'CONNECTING…');
    await loadLoggedAlerts();
    try {
      const rows = await fetchLiveRows();
      state.rows = rows;
      state.byTicker = new Map(rows.map((r) => [r.ticker, r]));
      rankAndScore(state.rows);
      state.lastRefresh = new Date();
      setBadge('live', 'LIVE — demo API');
      afterData();
      scheduleNext();
    } catch (err) {
      console.error(err);
      setBadge('error', 'DISCONNECTED');
      const le = $('#liveError'); if (le) le.style.display = 'block';
      const t = $('#liveErrorText');
      if (t) t.textContent = String(err.message || err) + ' — this browser may be unable to reach the demo API (network or CORS).';
      const mb = $('#marketsBody');
      if (mb) mb.innerHTML = '<tr class="empty-row"><td colspan="10">Live data unavailable. The committed server log is still shown in the alerts panel; click “Load simulated feed” to explore the UI.</td></tr>';
      renderFeeds();
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const hashTopic = (location.hash || '').replace('#', '').toLowerCase();
    if (hashTopic === 'all' || TOPIC_BY_ID[hashTopic]) state.topic = hashTopic;
    state.chart = new PriceChart($('#priceChart'), { rangeSec: 300 });

    $('#topicChips').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-topic]');
      if (!btn) return;
      state.topic = btn.dataset.topic;
      afterData();
    });

    $$('.range-btn').forEach((btn) => btn.addEventListener('click', () => {
      $$('.range-btn').forEach((b) => b.classList.toggle('active', b === btn));
      state.chart.setRange(parseInt(btn.dataset.sec, 10));
      state.candle.rangeSec = null; // force a re-fetch at the new resolution
      backfillChart();
    }));

    $('#pauseBtn').addEventListener('click', () => {
      state.paused = !state.paused;
      $('#pauseBtn').textContent = state.paused ? '▶ Resume' : '⏸ Pause';
      $('#pauseBtn').classList.toggle('active', state.paused);
      if (!state.paused) refresh();
    });
    $('#soundToggle').addEventListener('click', () => {
      state.sound = !state.sound;
      $('#soundToggle').classList.toggle('active', state.sound);
      $('#soundToggle').textContent = state.sound ? '🔔 Sound on' : '🔕 Sound off';
    });
    $('#simFallbackBtn').addEventListener('click', () => start(true));
    $('#liveRetryBtn').addEventListener('click', () => { clearTimeout(state.timer); start(false); });
    $('#clearFeedsBtn').addEventListener('click', () => { state.sessionAlerts = []; renderFeeds(); toast('Session alerts cleared (the committed server log is kept)'); });
    $('#exportAlertsBtn').addEventListener('click', () => {
      const header = 'source,ts,iso,ticker,topic,direction,delta_usd,from_usd,to_usd,model_score,move_ref,source_url\n';
      const body = [...state.logged, ...state.sessionAlerts]
        .sort((a, b) => a.ts - b.ts)
        .map((a) => [a.logged ? 'server' : 'session', a.ts, new Date(a.ts).toISOString(), a.ticker, a.topic, a.direction,
          a.delta != null ? a.delta : (a.direction === 'down' ? -alertSeverity(a) : alertSeverity(a)),
          a.from_price ?? '', a.price ?? a.to_price ?? '', a.score ?? '', a.move ?? '', a.source_url ?? '']
          .map((v) => csvCell(v)).join(',')).join('\n');
      const url = URL.createObjectURL(new Blob([header + body], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'tradebot1-alerts.csv'; a.click();
      URL.revokeObjectURL(url);
    });

    $('#paperBuyBtn').addEventListener('click', () => {
      const r = state.byTicker.get(state.selectedTicker);
      if (!r) return;
      const qty = Math.max(1, parseInt($('#paperQty').value, 10) || 1);
      const price = r.yesAsk ?? r.price;
      if (price == null) { toast('No ask price available yet'); return; }
      const res = PaperPortfolio.buy({ ticker: r.ticker, topic: r.topic, title: r.title, qty, price });
      toast(res.ok ? `Paper BUY ${qty} × ${r.ticker} @ $${price.toFixed(2)} (fee ${fmtUsd(res.fee)})` : res.error, 3500);
    });

    $('#demoBuyBtn').addEventListener('click', async () => {
      const r = state.byTicker.get(state.selectedTicker);
      if (!r) return;
      const settings = store.get('settings', {});
      if (!settings.enableOrders) { toast('Demo order execution is disabled. Enable it in Portfolio → Settings (demo keys required).', 4000); return; }
      const qty = Math.max(1, parseInt($('#paperQty').value, 10) || 1);
      const price = r.yesAsk ?? r.price;
      if (!window.confirm(`DEMO ORDER: Buy ${qty} YES of ${r.ticker} @ $${(price ?? 0).toFixed(2)} on the Kalshi DEMO account? (Mock funds — not real money.)`)) return;
      const res = await Kalshi.createOrderV2({ ticker: r.ticker, side: 'yes', count: qty, price });
      if (res.ok) toast('Demo order accepted (HTTP 201). Accepted is not filled — check Portfolio → Demo account for remaining count.', 5000);
      else toast('Order failed (HTTP ' + (res.status || 'network') + '): ' + JSON.stringify(res.data || res.error).slice(0, 300), 6000);
    });

    renderFeeds();
    start(false);
  });

  function csvCell(v) {
    const s = String(v == null ? '' : v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
})();
