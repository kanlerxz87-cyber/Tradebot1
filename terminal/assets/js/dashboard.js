/* dashboard.js — live dashboard orchestration.
   Live mode: polls the Kalshi demo REST API from the browser.
   Fallback:   clearly-labeled simulated feed when the API is unreachable.
   Alerting:   AlertEngine fires on moves >= $0.10 (session or 2-minute window). */
'use strict';

(function () {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    simulated: false,
    paused: false,
    topic: 'all',
    rows: [],             // normalized rows currently shown
    selectedTicker: null,
    pollMs: 4000,
    backoffUntil: 0,
    engine: new AlertEngine(90000),
    chart: null,
    alerts: store.get('alerts', []),
    sound: false,
    rand: SimulatedFeed.rng(20261122),
    ws: null,
    lastRefresh: null,
  };

  const DEFAULT_POLL = 4000;
  const BACKOFF_POLL = 15000;

  /* ---------------- helpers ---------------- */
  const mid = (r) => ((r.yesBid ?? r.last ?? 0.5) + (r.yesAsk ?? r.last ?? 0.5)) / 2;

  function normalizeRow(ev, m) {
    const topic = m._topic || classifyMarket({ ...m, category: m.category || (ev && ev.category), series_ticker: m.series_ticker || (ev && ev.series_ticker) });
    const yesBid = Kalshi.priceOf(m, 'bid');
    const yesAsk = Kalshi.priceOf(m, 'ask');
    const last = Kalshi.priceOf(m, 'last') ?? (yesBid != null && yesAsk != null ? (yesBid + yesAsk) / 2 : null);
    const prev = Kalshi.priceOf(m, 'prev');
    const vol = Kalshi.volumeOf(m);
    const vol24h = Kalshi.volume24hOf(m);
    const oi = Kalshi.openInterestOf(m);
    const notional = vol * (last ?? 0.5);
    const spread = yesBid != null && yesAsk != null ? yesAsk - yesBid : null;
    return {
      ticker: m.ticker, eventTicker: m.event_ticker || (ev && ev.event_ticker),
      title: (ev && (ev.title || ev.sub_title)) || m.title || m.ticker,
      marketTitle: m.yes_sub_title || m.title || '',
      topic, ev, m,
      yesBid, yesAsk, noBid: Kalshi.noBidOf(m), noAsk: Kalshi.noAskOf(m), last, prev,
      vol, vol24h, oi, notional, spread,
      roi: last && last > 0 ? (1 - last) / last : null,
      sim: !!m._sim,
      url: 'https://kalshi.com/markets/' + String((m.series_ticker || (ev && ev.series_ticker) || '')).toLowerCase(),
    };
  }

  function rankAndScore(rows) {
    const sorted = [...rows].sort((a, b) => b.notional - a.notional);
    sorted.forEach((r, i) => { r.volRank = rows.length > 1 ? i / (rows.length - 1) : 0; });
    for (const r of rows) {
      r.modelScore = Model.score(null, {
        volRank: r.volRank,
        spread: r.spread ?? 0.1,
        moveAbs: r.prev != null && r.last != null ? Math.abs(r.last - r.prev) : 0,
        price: r.last ?? 0.5,
        openInterest: r.oi,
      });
    }
  }

  function setBadge(mode, text) {
    const el = $('#connectionBadge');
    el.className = 'badge ' + (mode === 'live' ? 'live' : mode === 'sim' ? 'sim' : mode === 'error' ? 'err' : 'info');
    el.textContent = text;
  }

  function topicFiltered() {
    return state.rows.filter(r => state.topic === 'all' || r.topic === state.topic);
  }

  /* ---------------- data loading ---------------- */
  async function fetchLiveRows() {
    const res = await Kalshi.getEvents({ status: 'open', limit: 200 });
    if (!res.ok) {
      const err = new Error('Kalshi demo API request failed (HTTP ' + (res.status || 'network/CORS') + (res.error ? ': ' + res.error : '') + ')');
      err.status = res.status || 0;
      throw err;
    }
    const flat = await Kalshi.flattenEvents(res);
    return flat.map(({ event, market }) => normalizeRow(event, market)).filter(r => r.topic);
  }

  function simulatedRows() {
    return SimulatedFeed.makeSnapshot(Math.floor(Date.now() / 60000))
      .map(({ event, market }) => normalizeRow(event, market));
  }

  function simulateTick() {
    for (const r of state.rows) {
      const m = r.m;
      const newLast = SimulatedFeed.stepPrice(r.last ?? 0.5, state.rand);
      r.prev = r.last;
      r.last = newLast;
      r.yesBid = Math.max(0.01, newLast - 0.01);
      r.yesAsk = Math.min(0.99, newLast + 0.01);
      r.vol = (r.vol || 0) + Math.round(state.rand() * 40);
      r.notional = r.vol * newLast;
      r.spread = 0.02;
      m.volume_fp = String(r.vol);
    }
  }

  async function refresh() {
    if (state.paused) return;
    try {
      if (state.simulated) {
        simulateTick();
        state.rows.forEach(r => { r.modelScore = Math.round(r.modelScore); });
        rankAndScore(state.rows);
        afterData(false);
        return;
      }
      const rows = await fetchLiveRows();
      if (Date.now() < state.backoffUntil) return; // cooling off after 429
      state.rows = rows;
      rankAndScore(state.rows);
      setBadge('live', 'LIVE — demo API');
      state.pollMs = DEFAULT_POLL;
      state.lastRefresh = new Date();
      afterData(false);
    } catch (err) {
      console.warn('refresh failed', err);
      if (err.status === 429) {
        state.backoffUntil = Date.now() + 30000;
        state.pollMs = BACKOFF_POLL;
        setBadge('error', 'RATE LIMITED — backing off');
        return;
      }
      setBadge('error', 'DISCONNECTED');
      $('#liveError').style.display = 'block';
      $('#liveErrorText').textContent = String(err.message || err) + ' — likely causes: browser cannot reach the demo host (network/CORS), or you are offline. You can load the clearly-labeled simulated feed instead.';
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
    for (const t of TOPICS) counts[t.id] = state.rows.filter(r => r.topic === t.id).length;
    $('#topicChips').innerHTML = [['all', 'All topics'], ...TOPICS.map(t => [t.id, t.short])]
      .map(([id, label]) => `<button class="chip ${state.topic === id ? 'active' : ''}" data-topic="${id}">${label}<span class="count">${counts[id] ?? 0}</span></button>`)
      .join('');
  }

  function renderTable() {
    const rows = topicFiltered();
    $('#marketCount').textContent = String(rows.length);
    const tbody = $('#marketsBody');
    if (!rows.length) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="10">No markets in this topic right now. (Demo environments refresh constantly.)</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr data-ticker="${escapeHtml(r.ticker)}" class="${r.ticker === state.selectedTicker ? 'selected' : ''}">
        <td><span class="badge topic-${r.topic}">${escapeHtml((TOPIC_BY_ID[r.topic] || {}).short || '?')}</span></td>
        <td style="max-width:340px" title="${escapeHtml(r.title)}">${escapeHtml(truncate(r.title, 88))}</td>
        <td class="num">${fmtCents(r.last)}</td>
        <td class="num ${(r.prev != null && r.last != null && r.last - r.prev >= 0) ? 'up' : 'down'}">${r.prev != null && r.last != null ? fmtSignedUsd(r.last - r.prev) : '—'}</td>
        <td class="num">${fmtContracts(r.vol)}</td>
        <td class="num">${fmtUsd(r.notional, 0)}</td>
        <td class="num">${fmtCents(r.spread)}</td>
        <td class="num">${r.roi != null ? (r.roi * 100).toFixed(0) + '%' : '—'}</td>
        <td class="num"><span class="${r.modelScore >= 65 ? 'up' : 'muted'}">${r.modelScore}</span></td>
        <td>${r.sim ? '<span class="badge sim">SIM</span>' : ''}</td>
      </tr>`).join('');
    tbody.querySelectorAll('tr[data-ticker]').forEach(tr => tr.addEventListener('click', () => selectMarket(tr.dataset.ticker)));
  }

  function truncate(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

  function renderKPIs() {
    const r = state.rows.find(x => x.ticker === state.selectedTicker);
    if (!r) return;
    $('#selTicker').textContent = r.ticker + (r.sim ? ' · SIMULATED' : '');
    $('#selTitle').textContent = r.title;
    $('#kBid').textContent = fmtCents(r.yesBid);
    $('#kAsk').textContent = fmtCents(r.yesAsk);
    $('#kLast').textContent = fmtCents(r.last);
    $('#kVol').textContent = fmtContracts(r.vol);
    $('#k24h').textContent = fmtContracts(r.vol24h);
    $('#kOI').textContent = fmtContracts(r.oi);
    $('#kSpread').textContent = fmtCents(r.spread);
    $('#kNotional').textContent = fmtUsd(r.notional, 0);
    $('#kRoi').textContent = r.roi != null ? '+' + (r.roi * 100).toFixed(1) + '% if YES' : '—';
    const v = Model.verdict(r.modelScore);
    $('#kModel').textContent = `${r.modelScore} — ${v.label}`;
    $('#kModel').className = 'v ' + v.cls;
    const move = r.prev != null && r.last != null ? r.last - r.prev : null;
    $('#kMove').textContent = move != null ? fmtSignedUsd(move) : '—';
    $('#kMove').className = 'v ' + (move == null ? 'flat' : move >= 0 ? 'up' : 'down');
  }

  async function renderBook() {
    const r = state.rows.find(x => x.ticker === state.selectedTicker);
    if (!r) return;
    let book = null;
    if (r.sim) {
      book = SimulatedFeed.syntheticOrderbook(r.last ?? 0.5, (r.ticker.length * 2654435761) >>> 0);
    } else {
      const res = await Kalshi.getOrderbook(r.ticker);
      if (res.ok) book = Kalshi.normalizeBook(res.data);
    }
    if (!book) { $('#bookNote').textContent = 'Order book unavailable right now.'; return; }
    const maxQty = Math.max(1, ...book.yes.slice(0, 8).map(([, q]) => q), ...book.no.slice(0, 8).map(([, q]) => q));
    const cum = (levels) => {
      let c = 0; return levels.map(([p, q]) => { c += q; return { p, q, cum: c, dollars: c * p }; });
    };
    $('#bidsLadder').innerHTML = cum(book.yes.slice(0, 8)).map(({ p, q, cum, dollars }) => `
      <div class="ladder-row bid"><span>${fmtCents(p)}</span><div class="bar" style="width:${(q / maxQty) * 100}%"></div><span style="text-align:right">${fmtContracts(q)} <span class="muted">(${fmtContracts(cum)} cum)</span></span></div>`).join('')
      || '<div class="ladder-row"><span class="muted">No bids</span></div>';
    $('#asksLadder').innerHTML = cum(book.no.slice(0, 8)).map(({ p, q, cum, dollars }) => `
      <div class="ladder-row ask"><span>${fmtCents(p)}</span><div class="bar" style="width:${(q / maxQty) * 100}%"></div><span style="text-align:right">${fmtContracts(q)} <span class="muted">(${fmtContracts(cum)} cum)</span></span></div>`).join('')
      || '<div class="ladder-row"><span class="muted">No offers</span></div>';
    const bidDepth = book.yes.slice(0, 8).reduce((s, [, q]) => s + q, 0);
    const askDepth = book.no.slice(0, 8).reduce((s, [, q]) => s + q, 0);
    $('#bookNote').innerHTML = `YES bid depth (top 8): <strong>${fmtContracts(bidDepth)}</strong> contracts · NO bid depth (top 8): <strong>${fmtContracts(askDepth)}</strong> contracts. A NO bid at price <code>p</code> implies a YES offer at <code>1 − p</code>. ${r.sim ? '<span class="badge sim">SIMULATED</span>' : 'Source: GET /markets/{ticker}/orderbook (public)'}`;
  }

  function renderFeeds() {
    const all = $('#feedAll');
    const model = $('#feedModel');
    const mk = (a) => `
      <div class="chat-msg ${a.direction}" data-ticker="${escapeHtml(a.ticker)}" role="log">
        <div class="meta"><span>${escapeHtml((TOPIC_BY_ID[a.topic] || {}).short || a.topic || '')} · ${fmtTime(a.ts)}</span><span>MODEL ${a.score ?? '—'}</span></div>
        <div><span class="ticker">${escapeHtml(a.ticker)}</span> <strong class="${a.direction === 'up' ? 'up' : 'down'}">${a.direction === 'up' ? '▲' : '▼'} ${fmtSignedUsd(a.delta)}</strong> → $${a.price.toFixed(2)}</div>
        <div class="muted" style="margin-top:2px">${escapeHtml(truncate(a.title, 110))}</div>
      </div>`;
    const sorted = [...state.alerts].sort((a, b) => b.ts - a.ts).slice(0, 80);
    all.innerHTML = sorted.length ? sorted.map(mk).join('') : '<div class="muted small" style="padding:12px">No alerts yet this session. Alerts fire when a contract moves ≥ $0.10 (vs session reference or a 2-minute window).</div>';
    const modelAlerts = sorted.filter(a => (a.score ?? 0) >= Model.MODEL_FEED_THRESHOLD);
    model.innerHTML = modelAlerts.length ? modelAlerts.map(mk).join('') : '<div class="muted small" style="padding:12px">No model-approved (score ≥ 65) swing alerts yet. The model favors liquid, tight-spread markets with decisive moves. See the scoring rubric below.</div>';
    $('#feedAllCount').textContent = String(sorted.length);
    $('#feedModelCount').textContent = String(modelAlerts.length);
    all.querySelectorAll('.chat-msg[data-ticker]').forEach(el => el.addEventListener('click', () => selectMarket(el.dataset.ticker)));
    model.querySelectorAll('.chat-msg[data-ticker]').forEach(el => el.addEventListener('click', () => selectMarket(el.dataset.ticker)));
  }

  function pushAlert(a) {
    a.score = a.score ?? (state.rows.find(r => r.ticker === a.ticker) || {}).modelScore ?? null;
    state.alerts.push(a);
    if (state.alerts.length > 300) state.alerts = state.alerts.slice(-300);
    store.set('alerts', state.alerts.slice(-100));
    renderFeeds();
    if (a.ticker === state.selectedTicker) {
      showMoveBanner(a);
      renderDrivers(a);
    }
    if (state.sound) beep(a.direction);
  }

  function showMoveBanner(a) {
    const el = $('#moveBanner');
    el.style.display = 'block';
    el.innerHTML = `<strong>${a.direction === 'up' ? '▲ SWING UP' : '▼ SWING DOWN'} ${fmtSignedUsd(a.delta)}</strong> on <code>${escapeHtml(a.ticker)}</code> → $${a.price.toFixed(2)} (${a.move === 'session' ? 'vs session reference' : 'within 2 minutes'}). Possible drivers below — these are links to check, not proven causation.`;
  }

  function renderDrivers(a) {
    const links = driverLinks(a.topic, a.title.replace(/^SIM: /, ''));
    $('#driversRow').innerHTML = links.map(l => `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.label)} ↗</a>`).join('');
    $('#driversWrap').style.display = 'block';
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
    for (const r of state.rows) {
      if (r.last == null) continue;
      const a = state.engine.update(r.ticker, r.last, { ticker: r.ticker, title: r.title, topic: r.topic });
      if (a) { a.score = r.modelScore; pushAlert(a); }
    }
  }

  function afterData() {
    renderTopicChips();
    renderTable();
    if (!state.selectedTicker || !state.rows.find(r => r.ticker === state.selectedTicker)) {
      const first = topicFiltered()[0];
      if (first) state.selectedTicker = first.ticker;
    }
    renderKPIs();
    const r = state.rows.find(x => x.ticker === state.selectedTicker);
    if (r && r.last != null) state.chart.addPoint(Date.now(), r.last);
    renderBook();
    runAlertScan();
    $('#refreshInfo').textContent = 'Tracking ' + state.rows.length + ' contracts · updated ' + fmtTime(Date.now()) + (state.simulated ? ' · SIMULATED FEED' : '');
  }

  function selectMarket(ticker) {
    state.selectedTicker = ticker;
    const r = state.rows.find(x => x.ticker === ticker);
    state.chart.clear();
    renderTopicChips();
    renderTable();
    renderKPIs();
    renderBook();
    if (r && r.last != null) state.chart.addPoint(Date.now(), r.last);
  }

  /* ---------------- boot ---------------- */
  async function start(simulated) {
    state.simulated = !!simulated;
    state.rows = simulated ? simulatedRows() : [];
    if (simulated) {
      rankAndScore(state.rows);
      setBadge('sim', 'SIMULATED FEED');
      $('#liveError').style.display = 'none';
      $('#simBanner').style.display = 'block';
      state.lastRefresh = new Date();
      afterData();
      scheduleNext();
      return;
    }
    $('#simBanner').style.display = 'none';
    setBadge('info', 'CONNECTING…');
    try {
      state.rows = await fetchLiveRows();
      rankAndScore(state.rows);
      state.lastRefresh = new Date();
      setBadge('live', 'LIVE — demo API');
      afterData();
      scheduleNext();
    } catch (err) {
      console.error(err);
      setBadge('error', 'DISCONNECTED');
      $('#liveError').style.display = 'block';
      $('#liveErrorText').textContent = String(err.message || err) + ' — the browser may be unable to reach the demo API (network or CORS). Load the simulated feed to explore the UI.';
      $('#marketsBody').innerHTML = '<tr class="empty-row"><td colspan="10">Live data unavailable. Click “Load simulated feed” above.</td></tr>';
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
      renderTopicChips();
      renderTable();
    });

    $$('.range-btn').forEach(btn => btn.addEventListener('click', () => {
      $$('.range-btn').forEach(b => b.classList.toggle('active', b === btn));
      state.chart.setRange(parseInt(btn.dataset.sec, 10));
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
    $('#clearFeedsBtn').addEventListener('click', () => { state.alerts = []; store.set('alerts', []); renderFeeds(); toast('Alert history cleared'); });
    $('#exportAlertsBtn').addEventListener('click', () => {
      const header = 'ts,iso,ticker,topic,direction,delta_usd,price_usd,model_score,move_ref\n';
      const body = state.alerts.map(a => [a.ts, new Date(a.ts).toISOString(), a.ticker, a.topic, a.direction, a.delta, a.price, a.score ?? '', a.move].join(',')).join('\n');
      const url = URL.createObjectURL(new Blob([header + body], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'tradebot1-alerts.csv'; a.click();
      URL.revokeObjectURL(url);
    });

    $('#paperBuyBtn').addEventListener('click', () => {
      const r = state.rows.find(x => x.ticker === state.selectedTicker);
      if (!r) return;
      const qty = Math.max(1, parseInt($('#paperQty').value, 10) || 1);
      const price = r.yesAsk ?? r.last;
      if (price == null) { toast('No ask price available yet'); return; }
      const res = PaperPortfolio.buy({ ticker: r.ticker, topic: r.topic, title: r.title, qty, price });
      toast(res.ok ? `Paper BUY ${qty} × ${r.ticker} @ $${price.toFixed(2)} (fee ${fmtUsd(res.fee)})` : res.error, 3500);
    });

    $('#demoBuyBtn').addEventListener('click', async () => {
      const r = state.rows.find(x => x.ticker === state.selectedTicker);
      if (!r) return;
      const settings = store.get('settings', {});
      if (!settings.enableOrders) { toast('Demo order execution is disabled. Enable it in Portfolio → Settings (demo keys required).', 4000); return; }
      const qty = Math.max(1, parseInt($('#paperQty').value, 10) || 1);
      const price = r.yesAsk ?? r.last;
      if (!window.confirm(`DEMO ORDER: Buy ${qty} YES of ${r.ticker} @ $${(price ?? 0).toFixed(2)} on the Kalshi DEMO account? (Mock funds — not real money.)`)) return;
      const res = await Kalshi.createOrderV2({ ticker: r.ticker, side: 'yes', count: qty, price });
      if (res.ok) toast('Demo order placed. Check Portfolio → Demo account.', 4000);
      else toast('Order failed (HTTP ' + (res.status || 'network') + '): ' + JSON.stringify(res.data || res.error).slice(0, 300), 6000);
    });

    renderFeeds();
    start(false);
  });
})();
