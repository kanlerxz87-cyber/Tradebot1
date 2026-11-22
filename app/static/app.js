/* Kalshi live dashboard - no build step, no external dependencies.
 *
 * Everything rendered here comes from the JSON API. Numbers are formatted from
 * the strings the server received from Kalshi; the client never invents a
 * value. A missing value renders as "--".
 */
'use strict';

const state = {
  topic: 'all',
  sort: 'dollar_volume',
  selected: null,
  rangeSeconds: 60,
  lastAlertId: 0,
  lastSelectiveId: 0,
  alerts: [],
  selective: [],
  markets: [],
  topicMeta: {},
  positions: [],
  timer: null,
  chartTimer: null,
};

const $ = (sel) => document.querySelector(sel);
const fmtMoney = (v, places = 2) => (v === null || v === undefined || v === '')
  ? '--' : `$${Number(v).toLocaleString(undefined, {minimumFractionDigits: places, maximumFractionDigits: places})}`;
const fmtCents = (v) => (v === null || v === undefined || v === '') ? '--' : `${Math.round(Number(v) * 100)}c`;
const fmtNum = (v, places = 0) => (v === null || v === undefined || v === '') ? '--'
  : Number(v).toLocaleString(undefined, {maximumFractionDigits: places});
const fmtTime = (ts) => {
  if (!ts) return '--';
  const d = new Date(Number(ts) * 1000);
  return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
};
const fmtDate = (s) => {
  if (!s) return '--';
  const d = new Date(s);
  if (isNaN(d.getTime())) return '--';
  return d.toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
};
const esc = (s) => String(s === null || s === undefined ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

async function getJSON(url) {
  const res = await fetch(url, {headers: {'Accept': 'application/json'}});
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/* ------------------------------------------------------------------ topics */
function renderTabs(meta) {
  state.topicMeta = meta || {};
  const nav = $('#topic-tabs');
  const labels = {all: 'All'};
  Object.entries(meta || {}).forEach(([k, v]) => { labels[k] = v.label; });
  nav.innerHTML = '';
  Object.entries(labels).forEach(([key, label]) => {
    const b = document.createElement('button');
    b.className = 'tab' + (key === state.topic ? ' active' : '');
    b.dataset.topic = key;
    b.textContent = label;
    b.addEventListener('click', () => {
      state.topic = key;
      document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.topic === key));
      refreshMarkets();
    });
    nav.appendChild(b);
  });
}

/* ------------------------------------------------------------------- chats */
function alertCard(a, selective) {
  const dir = a.direction === 'up' ? 'up' : 'down';
  const delta = Number(a.delta);
  const sign = delta > 0 ? '+' : '';
  const news = a.news || {};
  const headlines = (news.headlines || []).map(h => {
    const tag = h.trusted ? '<span class="badge confirmed">trusted</span> ' : '';
    return `<a href="${esc(h.link)}" target="_blank" rel="noopener">${tag}${esc(h.title)}</a>` +
      `<span class="muted">${esc(h.source || '')} ${h.published_utc ? '· ' + esc(h.published_utc) : ''}</span>`;
  }).join('');
  const sources = (news.contract_sources || []).map(s =>
    `<a href="${esc(s.url)}" target="_blank" rel="noopener">settles via ${esc(s.name)}</a>`).join(' ');
  const newsBlock = (headlines || sources)
    ? `<div class="news"><strong>Possible catalyst</strong>${headlines}${sources}</div>`
    : (news.status === 'error'
        ? `<div class="news"><span class="muted">Headline lookup unavailable (${esc(news.note || 'error')}).</span></div>`
        : `<div class="news"><span class="muted">No headline in the lookback window; this is a quote-driven move.</span></div>`);
  const scoreBadge = selective
    ? `<span class="badge score-high">score ${esc(a.score)}</span>` : '';
  return `<div class="msg ${dir}">
    <div class="row1">
      <span class="tick">${esc(fmtTime(a.ts))} · ${esc(a.ticker)}</span>
      <span><span class="delta">${sign}${fmtCents(a.delta)}</span> ${scoreBadge}</span>
    </div>
    <div class="title">${a.page_url ? `<a href="${esc(a.page_url)}" target="_blank" rel="noopener">${esc(a.title || a.ticker)}</a>` : esc(a.title || a.ticker)}</div>
    <div class="meta">
      <span class="tag">${esc(a.topic || 'other')}</span>
      <span>${fmtCents(a.from_price)} → ${fmtCents(a.to_price)}</span>
      <span class="badge ${esc(a.confidence)}">${esc(a.confidence)}</span>
      <span>${esc(a.window_s)}s</span>
      ${a.depth_10c ? `<span>depth ${fmtNum(a.depth_10c)}</span>` : ''}
      ${a.liquidity ? `<span>liq ${fmtMoney(a.liquidity, 0)}</span>` : ''}
    </div>
    ${newsBlock}
  </div>`;
}

function paintChat(el, alerts, selective) {
  // The container is column-reverse, so newest-first DOM reads top-down.
  el.innerHTML = alerts.length
    ? alerts.map(a => alertCard(a, selective)).join('')
    : `<div class="empty">Waiting for a ≥ $0.10 move…</div>`;
}

async function refreshAlerts() {
  try {
    const [all, sel] = await Promise.all([
      getJSON(`/api/alerts?limit=40&topic=${encodeURIComponent(state.topic)}`),
      getJSON('/api/alerts/selective?limit=40'),
    ]);
    state.alerts = (all.alerts || []).slice().reverse();
    state.selective = (sel.alerts || []).slice().reverse();
    paintChat($('#chat-all'), state.alerts, false);
    paintChat($('#chat-selective'), state.selective, true);
    const counts = await getJSON('/api/analytics');
    const total = (counts.groups || []).length ? null : null;
    $('#stat-alerts').textContent = fmtNum(state.alerts.length ? undefined : 0) === '0' ? '0' : '--';
  } catch (err) {
    console.warn('alerts', err);
  }
}

/* ----------------------------------------------------------------- markets */
function marketRow(m) {
  const price = m.price !== null && m.price !== undefined ? Number(m.price) : null;
  const bid = m.yes_bid !== null && m.yes_bid !== undefined ? Number(m.yes_bid) : null;
  const ask = m.yes_ask !== null && m.yes_ask !== undefined ? Number(m.yes_ask) : null;
  const hasMove = m.last_move !== undefined && m.last_move !== null;
  const moveCls = hasMove ? (Number(m.last_move) > 0 ? 'up' : 'down') : '';
  return `<tr data-ticker="${esc(m.ticker)}" class="${state.selected === m.ticker ? 'selected' : ''}">
    <td class="uniq"><div class="cell-title">${m.page_url ? `<a href="${esc(m.page_url)}" target="_blank" rel="noopener">${esc(m.title || m.ticker)}</a>` : esc(m.title || m.ticker)}</div>
      <div class="cell-ticker">${esc(m.ticker)}${m.subtitle ? ' · ' + esc(m.subtitle) : ''}</div></td>
    <td><span class="tag">${esc(m.topic || '')}</span></td>
    <td class="num ${moveCls}">${fmtCents(price)}</td>
    <td class="num">${fmtCents(bid)}</td>
    <td class="num">${fmtCents(ask)}</td>
    <td class="num">${m.spread ? fmtCents(m.spread) : '--'}</td>
    <td class="num">${m.depth_10c ? fmtNum(m.depth_10c) : '--'}</td>
    <td class="num">${m.liquidity ? fmtMoney(m.liquidity, 0) : '--'}</td>
    <td class="num">${fmtNum(m.volume_fp, 0)}</td>
    <td>${esc(fmtDate(m.close_time))}</td>
    <td><a href="${esc(m.page_url || '#')}" target="_blank" rel="noopener">Kalshi ↗</a></td>
  </tr>`;
}

function sortMarkets(rows) {
  const key = state.sort;
  const copy = rows.slice();
  copy.sort((a, b) => {
    const na = Number(a[key] ?? 0), nb = Number(b[key] ?? 0);
    if (key === 'close_time') {
      const ta = a.close_time ? Date.parse(a.close_time) : Infinity;
      const tb = b.close_time ? Date.parse(b.close_time) : Infinity;
      return ta - tb;
    }
    return nb - na;
  });
  return copy;
}

function paintMarkets() {
  const body = $('#market-body');
  const rows = sortMarkets(state.markets);
  body.innerHTML = rows.length
    ? rows.map(marketRow).join('')
    : '<tr><td colspan="11" class="empty">No live markets in this topic right now.</td></tr>';
  body.querySelectorAll('tr[data-ticker]').forEach(tr => {
    tr.addEventListener('click', () => selectMarket(tr.dataset.ticker));
  });
}

async function refreshMarkets() {
  try {
    const data = await getJSON(`/api/markets?topic=${encodeURIComponent(state.topic)}&limit=120`);
    // Attach the most recent alert delta so the price cell can colour the move.
    const byTicker = {};
    state.alerts.forEach(a => { byTicker[a.ticker] = a.delta; });
    state.markets = (data.markets || []).map(m => ({
      ...m, last_move: byTicker[m.ticker] !== undefined ? byTicker[m.ticker] : null,
    }));
    paintMarkets();
  } catch (err) { console.warn('markets', err); }
}

function selectMarket(ticker) {
  state.selected = ticker;
  paintMarkets();
  drawChart();
  const meta = state.markets.find(m => m.ticker === ticker);
  $('#chart-title').textContent = meta ? `· ${meta.title}` : `· ${ticker}`;
}

/* ------------------------------------------------------------------- chart */
async function drawChart() {
  const canvas = $('#chart');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 900;
  const cssH = 260;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 46, padR = 12, padT = 12, padB = 24;
  const plotW = cssW - padL - padR, plotH = cssH - padT - padB;

  ctx.fillStyle = '#0b0f14';
  ctx.fillRect(0, 0, cssW, cssH);

  if (!state.selected) {
    ctx.fillStyle = '#8b98a9';
    ctx.font = '12px Inter, sans-serif';
    ctx.fillText('Select a market above to chart its price.', padL, padT + 20);
    return;
  }

  let points = [];
  try {
    const data = await getJSON(`/api/charts/${encodeURIComponent(state.selected)}?range_seconds=${state.rangeSeconds}`);
    points = data.points || [];
  } catch (err) {
    ctx.fillStyle = '#ff5c5c';
    ctx.fillText('chart unavailable', padL, padT + 20);
    return;
  }

  const now = Date.now() / 1000;
  const t0 = now - state.rangeSeconds, t1 = now;
  const xs = (t) => padL + ((t - t0) / Math.max(1, (t1 - t0))) * plotW;

  // Fixed 0..100c axis keeps every chart comparable; the band is the alert rule.
  const ys = (p) => padT + (1 - p) * plotH;

  // grid + y labels (cents)
  ctx.strokeStyle = '#1c242f'; ctx.lineWidth = 1;
  ctx.fillStyle = '#8b98a9'; ctx.font = '10px ui-monospace, monospace';
  [0, 0.25, 0.5, 0.75, 1].forEach(p => {
    const y = ys(p);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(cssW - padR, y); ctx.stroke();
    ctx.fillText(`${Math.round(p * 100)}c`, 8, y + 3);
  });

  // x labels
  const labelCount = 4;
  for (let i = 0; i <= labelCount; i++) {
    const t = t0 + ((t1 - t0) * i) / labelCount;
    const x = xs(t);
    const d = new Date(t * 1000);
    ctx.fillStyle = '#8b98a9';
    const label = state.rangeSeconds >= 3600
      ? d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
      : d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    const w = ctx.measureText(label).width;
    ctx.fillText(label, Math.min(Math.max(x - w / 2, padL), cssW - padR - w), cssH - 7);
  }

  if (!points.length) {
    ctx.fillStyle = '#8b98a9';
    ctx.font = '12px Inter, sans-serif';
    ctx.fillText('No samples in this window yet. The engine records a tick every poll.', padL + 8, padT + 20);
    return;
  }

  const lastPrice = points[points.length - 1].p;
  // ±$0.10 band
  const lo = Math.max(0, lastPrice - 0.10), hi = Math.min(1, lastPrice + 0.10);
  ctx.fillStyle = 'rgba(74,168,255,0.13)';
  ctx.fillRect(padL, ys(hi), plotW, ys(lo) - ys(hi));

  // price line
  ctx.strokeStyle = '#4aa8ff';
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  points.forEach((pt, i) => {
    const x = xs(pt.t), y = ys(pt.p);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // last price marker
  const lx = xs(points[points.length - 1].t), ly = ys(lastPrice);
  ctx.fillStyle = '#4aa8ff';
  ctx.beginPath(); ctx.arc(lx, ly, 2.6, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#e6edf3';
  ctx.font = '11px ui-monospace, monospace';
  ctx.fillText(`${Math.round(lastPrice * 100)}c`, Math.min(lx + 6, cssW - padR - 30), Math.max(ly - 6, padT + 8));

  // alert markers
  const alerts = state.alerts.filter(a => a.ticker === state.selected);
  ctx.fillStyle = '#ffb020';
  alerts.forEach(a => {
    const x = xs(Number(a.ts));
    if (x < padL || x > cssW - padR) return;
    const y = ys(Number(a.to_price));
    ctx.beginPath();
    ctx.moveTo(x, y - 5); ctx.lineTo(x + 5, y); ctx.lineTo(x, y + 5); ctx.lineTo(x - 5, y);
    ctx.closePath(); ctx.fill();
  });
}

/* --------------------------------------------------------------- portfolio */
function paintPortfolio(payload) {
  const rows = payload.strategies || [];
  $('#sim-mode').textContent = payload.mode === 'demo-mirrored'
    ? 'paper + mirrored to Kalshi demo orders' : 'paper only (no credentials)';
  $('#portfolio-body').innerHTML = rows.length ? rows.map(s => {
    const ret = Number(s.total_return_pct);
    const cls = ret > 0 ? 'up' : ret < 0 ? 'down' : '';
    return `<tr>
      <td><strong>${esc(s.name)}</strong><div class="cell-ticker">${esc(s.key)}</div></td>
      <td>${esc(s.category)}</td>
      <td class="num">${fmtMoney(s.starting_cash)}</td>
      <td class="num">${fmtMoney(s.cash)}</td>
      <td class="num">${fmtMoney(s.positions_value)}</td>
      <td class="num">${fmtMoney(s.equity)}</td>
      <td class="num ${cls}">${isNaN(ret) ? '--' : (ret > 0 ? '+' : '') + ret.toFixed(2) + '%'}</td>
      <td class="num">${fmtMoney(s.realized_pnl)}</td>
      <td class="num">${fmtMoney(s.fees_paid)}</td>
      <td class="num">${s.win_rate === null ? '--' : esc(s.win_rate) + '%'}</td>
      <td class="num">${(s.open_positions || []).length}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="11" class="empty">No strategies initialised.</td></tr>';

  const posRows = [];
  rows.forEach(s => (s.open_positions || []).forEach(p => {
    const unr = Number(p.unrealized);
    posRows.push(`<tr>
      <td>${esc(s.name)}</td>
      <td><div class="cell-title">${esc(p.ticker)}</div><div class="cell-ticker">${esc(p.side)} · ${esc(p.topic || '')}</div></td>
      <td class="num">${fmtNum(p.contracts, 2)}</td>
      <td class="num">${fmtCents(p.entry_price)}</td>
      <td class="num">${fmtCents(p.mark)}</td>
      <td class="num ${unr > 0 ? 'up' : unr < 0 ? 'down' : ''}">${fmtMoney(p.unrealized)}</td>
    </tr>`);
  }));
  $('#positions-body').innerHTML = posRows.length ? posRows.join('')
    : '<tr><td colspan="6" class="empty">No open positions</td></tr>';
}

function paintEvents(events) {
  $('#events-body').innerHTML = events.length ? events.map(e => {
    const statusCls = e.status === 'filled' ? 'up' : e.status === 'rejected' ? 'down' : '';
    return `<tr>
      <td class="muted">${esc(fmtTime(e.ts))}</td>
      <td>${esc(e.strategy_name || e.strategy)}</td>
      <td class="cell-ticker">${esc(e.ticker)}</td>
      <td>${esc(e.action || '')} ${esc(e.side || '')}</td>
      <td class="num">${fmtNum(e.contracts || e.proposed_contracts, 0)}</td>
      <td class="num">${fmtCents(e.price)}</td>
      <td class="${statusCls}">${esc(e.status || '')}${e.rejection ? ': ' + esc(e.rejection) : ''}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">No fills yet</td></tr>';
}

function paintAnalytics(payload) {
  const groups = payload.groups || [];
  $('#analytics-note').textContent = `${payload.trades_considered || 0} realised trades considered`;
  $('#analytics-body').innerHTML = groups.length ? groups.map(g => `<tr>
    <td>${esc(g.dimension)}</td><td>${esc(g.value)}</td>
    <td class="num">${fmtNum(g.trades)}</td>
    <td class="num">${fmtMoney(g.proceeds)}</td>
    <td class="num">${fmtMoney(g.fees)}</td>
    <td class="num">${fmtNum(g.settled)}</td>
  </tr>`).join('') : '<tr><td colspan="6" class="empty">No realised trades yet</td></tr>';
}

function paintResolutions(rows) {
  $('#resolution-body').innerHTML = rows.length ? rows.map(r => {
    const cls = r.result === 'yes' ? 'up' : r.result === 'no' ? 'down' : '';
    return `<tr>
      <td><div class="cell-title">${esc(r.title || r.ticker)}</div><div class="cell-ticker">${esc(r.ticker)}</div></td>
      <td><span class="tag">${esc(r.topic || '')}</span></td>
      <td class="${cls}"><strong>${r.result ? esc(r.result.toUpperCase()) : '--'}</strong></td>
      <td class="num">${fmtCents(r.settlement_value)}</td>
      <td>${r.determined_ts ? esc(fmtDate(new Date(Number(r.determined_ts) * 1000).toISOString())) : '--'}</td>
      <td>${r.page_url ? `<a href="${esc(r.page_url)}" target="_blank" rel="noopener">Kalshi ↗</a>` : '--'}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="6" class="empty">Nothing resolved yet. Markets stay here until determination.</td></tr>';
}

/* ------------------------------------------------------------------ status */
function paintStatus(payload) {
  const s = payload.status || {};
  const dot = $('#status-dot');
  dot.className = 'dot ' + (s.running ? (s.last_error ? 'err' : 'live') : '');
  $('#last-update').textContent = `updated ${new Date().toLocaleTimeString()}`;
  $('#stat-tracked').textContent = fmtNum(s.tracked_size);
  const alertsEl = $('#stat-alerts');
  if (alertsEl) alertsEl.textContent = fmtNum((payload.alerts || []).length);
  $('#stat-selective').textContent = fmtNum((payload.selective_alerts || []).length);
  $('#stat-ws').textContent = s.ws_connected ? `WS · ${fmtNum(s.ws_messages)} msgs` : 'REST poll';
  $('#stat-ws').title = s.ws_connected
    ? 'Live websocket connected (authenticated handshake)'
    : 'No websocket: either no API key or the socket is reconnecting. REST polling continues.';
  const err = $('#engine-error');
  if (s.last_error) {
    err.classList.remove('hidden');
    err.textContent = `Engine: ${s.last_error}`;
  } else {
    err.classList.add('hidden');
  }
  if (payload.threshold) $('#rule').textContent = `≥ $${Number(payload.threshold).toFixed(2)} move`;
  if (payload.topic_meta) renderTabs(payload.topic_meta);
}

/* -------------------------------------------------------------------- loop */
async function refreshAll() {
  try {
    const data = await getJSON(`/api/state?topic=${encodeURIComponent(state.topic)}&limit=120`);
    paintStatus(data);
    state.markets = data.markets || [];
    const byTicker = {};
    (data.alerts || []).forEach(a => { byTicker[a.ticker] = a.delta; });
    state.markets = state.markets.map(m => ({...m, last_move: byTicker[m.ticker] ?? null}));
    state.alerts = (data.alerts || []).slice().reverse();
    state.selective = (data.selective_alerts || []).slice().reverse();
    paintChat($('#chat-all'), state.alerts.slice(-40).reverse(), false);
    paintChat($('#chat-selective'), state.selective.slice(-40).reverse(), true);
    paintMarkets();
    paintPortfolio(data.portfolio || {});
    paintEvents(data.events || []);
    paintResolutions(data.resolutions || []);
    const analytics = await getJSON('/api/analytics');
    paintAnalytics(analytics);
    if (data.counts) {
      $('#stat-alerts').textContent = fmtNum(data.counts.alerts);
      $('#stat-selective').textContent = fmtNum(data.counts.selective_alerts);
    }
    if (!state.selected && state.markets.length) selectMarket(state.markets[0].ticker);
    else drawChart();
    const cfg = await getJSON('/api/config');
    if (cfg.topics) {
      const meta = {};
      cfg.topics.forEach(t => { meta[t.key] = t; });
      renderTabs(meta);
    }
  } catch (err) {
    console.warn('state', err);
    $('#engine-error').classList.remove('hidden');
    $('#engine-error').textContent = `Cannot reach the engine: ${err.message}`;
  }
}

function wire() {
  $('#sort-select').addEventListener('change', (e) => { state.sort = e.target.value; paintMarkets(); });
  $('#refresh-btn').addEventListener('click', async () => {
    const btn = e => e;
    try { await fetch('/api/refresh', {method: 'POST'}); await refreshAll(); }
    catch (err) { console.warn(err); }
  });
  document.querySelectorAll('#range-buttons button').forEach(b => {
    b.addEventListener('click', () => {
      state.rangeSeconds = Number(b.dataset.sec);
      document.querySelectorAll('#range-buttons button').forEach(x => x.classList.toggle('active', x === b));
      drawChart();
    });
  });
  window.addEventListener('resize', () => drawChart());
}

async function boot() {
  wire();
  await refreshAll();
  // 5s state refresh: the chat is the live element, so it must feel immediate
  // without hammering the upstream API.
  state.timer = setInterval(refreshAll, 5000);
}

document.addEventListener('DOMContentLoaded', boot);
