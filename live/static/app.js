/* Kalshi live desk — vanilla JS, no build step, no dependencies.
 *
 * Data flow: fetch /api/state once, then subscribe to /api/stream (Server-Sent Events).
 * Each tick carries only the markets whose price changed, so the browser never needs to
 * poll 300 quotes. Everything rendered here comes from the server's response; nothing is
 * interpolated client-side.
 */
const S = {
  meta: null,
  raw: null,
  markets: new Map(),      // ticker -> market (mutable copy of the server row)
  events: {},              // topic -> [event]
  topic: 'gas',
  selected: null,          // ticker
  range: 300,
  series: [],              // [{t, mid}]
  book: null,
  alertsAll: [],
  alertsModel: [],
  equity: [],
  analysisGroup: 'byStrategy',
  lastAlertKey: null,
  connected: false,
};

const $ = (id) => document.getElementById(id);
const fmtMoney = (v, digits = 0) =>
  v == null || Number.isNaN(v) ? '—' : '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
const fmtNum = (v, digits = 0) =>
  v == null || Number.isNaN(v) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
const cents = (v) => (v == null ? '—' : Math.round(v * 100) + '¢');
const signed = (v) => (v == null ? '—' : (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toFixed(2));
const cls = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : '—');

async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(url + ' → ' + res.status);
  return res.json();
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  bindUI();
  tickClock();
  setInterval(tickClock, 1000);
  try {
    const state = await getJSON('/api/state');
    applyState(state);
    startStream();
  } catch (err) {
    $('modeBadge').textContent = 'offline';
    $('modeBadge').className = 'badge mode bad';
    $('marketRows').innerHTML = `<tr><td colspan="8" class="empty">Could not read /api/state — ${esc(err.message)}</td></tr>`;
  }
  setInterval(refreshState, 8000);
  setInterval(refreshSeries, 2500);
}

function tickClock() {
  $('clock').textContent = new Date().toLocaleTimeString([], { hour12: false });
}

function applyState(state) {
  S.raw = state;
  S.meta = state.meta;
  S.markets.clear();
  for (const [topic, events] of Object.entries(state.topics || {})) {
    for (const event of events) {
      for (const market of event.markets) {
        S.markets.set(market.ticker, market);
      }
    }
  }
  S.events = state.topics || {};
  S.alertsAll = state.alerts || [];
  S.alertsModel = S.alertsAll.filter((a) => a.selected);
  if (!S.selected) {
    const first = (S.events[S.topic] || [])[0];
    if (first) S.selected = first.markets[0].ticker;
  }
  renderMeta();
  renderKpis();
  renderTabs();
  renderEvents();
  renderFeeds();
  renderPortfolio(state.portfolio);
  renderAnalysis(state.portfolio);
  renderResolution(state);
  if (S.selected) selectMarket(S.selected, true);
  S.equity = (state.portfolio.equityCurve || []).map((p) => ({ t: new Date(p.ts).getTime(), equity: p.equity }));
  drawEquity();
}

function renderMeta() {
  const m = S.meta;
  const badge = $('modeBadge');
  badge.textContent = m.simulated ? 'SIMULATED' : 'LIVE';
  badge.className = 'badge mode ' + (m.simulated ? 'sim' : 'live');
  const banner = $('modeBanner');
  banner.hidden = false;
  banner.className = 'banner ' + (m.simulated ? 'sim' : 'live');
  $('bannerTitle').textContent = m.simulated ? 'SIMULATED TICKS' : 'LIVE DEMO API';
  $('bannerText').textContent = m.disclosure + ' Threshold ' + (m.threshold * 100).toFixed(0) + '¢, ' + m.intervalSeconds + 's cadence.';
  $('snapshotStamp').textContent = 'capture ' + (m.snapshot.capturedAt || '—') + ' · ' + m.snapshot.source;
  $('limits').innerHTML = (m.limits || []).map((l) => `<p>• ${esc(l)}</p>`).join('');
  $('sourceLine').textContent =
    'REST ' + m.endpoints.rest + ' · WebSocket ' + m.endpoints.websocket + ' · fee model ' +
    m.fees.model + ' (' + (m.fees.verified ? 'verified' : 'UNVERIFIED') + ').';
}

/* ------------------------------------------------------------------ KPIs */

function renderKpis() {
  let notional = 0;
  let markets = 0;
  let best = null;
  for (const events of Object.values(S.events)) {
    for (const event of events) {
      for (const m of event.markets) {
        markets += 1;
        notional += m.notional24h || 0;
        if (!best || (m.notional24h || 0) > (best.notional24h || 0)) best = m;
      }
    }
  }
  $('kpiNotional').textContent = fmtMoney(notional);
  $('kpiMarkets').textContent = fmtNum(markets);
  $('kpiMarketsFoot').textContent = Object.keys(S.events).map((k) => `${k} ${(S.events[k] || []).reduce((n, e) => n + e.markets.length, 0)}`).join(' · ');
  const hourAgo = Date.now() - 3600e3;
  const recent = S.alertsAll.filter((a) => new Date(a.at).getTime() >= hourAgo);
  $('kpiAlerts').textContent = fmtNum(recent.length);
  const biggest = S.alertsAll.reduce((acc, a) => (!acc || a.absDelta > acc.absDelta ? a : acc), null);
  $('kpiBiggest').textContent = biggest ? '$' + biggest.absDelta.toFixed(2) : '—';
  $('kpiBiggestFoot').textContent = biggest ? `${biggest.topic} · ${biggest.direction}` : 'this session';
  const folio = S.raw?.portfolio;
  if (folio) {
    $('kpiEquity').textContent = fmtMoney(folio.equity, 2);
    $('kpiEquity').className = cls(folio.totalPnl);
    $('kpiEquityFoot').textContent = `${signed(folio.totalPnl)} (${folio.roiPct >= 0 ? '+' : ''}${folio.roiPct}%)`;
    $('kpiPositions').textContent = `${folio.openPositions} / ${folio.closedTrades}`;
    $('kpiPositionsFoot').textContent = folio.winRate == null ? 'no closed trades yet' : folio.winRate + '% win rate';
  }
}

/* ------------------------------------------------------------------ topics + table */

function renderTabs() {
  const order = ['gas', 'elections', 'culture', 'crypto', 'golf'];
  $('topicTabs').innerHTML = order
    .map((topic) => {
      const events = S.events[topic] || [];
      const markets = events.reduce((n, e) => n + e.markets.length, 0);
      return `<button role="tab" data-topic="${topic}" class="${topic === S.topic ? 'active' : ''}">
        ${esc(S.meta.topics.find((t) => t.id === topic)?.label || topic)}
        <span class="tabcount">${markets}</span></button>`;
    })
    .join('');
  $('topicTabs').querySelectorAll('button').forEach((btn) => {
    btn.onclick = () => {
      S.topic = btn.dataset.topic;
      renderTabs();
      renderEvents();
      const first = (S.events[S.topic] || [])[0];
      if (first) selectMarket(first.markets[0].ticker, true);
    };
  });
}

function renderEvents() {
  const events = S.events[S.topic] || [];
  if (!events.length) {
    $('marketRows').innerHTML = '<tr><td colspan="8" class="empty">No markets captured for this topic.</td></tr>';
    return;
  }
  const rows = [];
  for (const event of events.slice(0, 14)) {
    rows.push(`<tr class="event-row"><td colspan="8">
      <span class="event-title">${esc(event.title || event.eventTicker)}</span>
      <span class="event-meta">${esc(event.eventTicker)} · ${event.markets.length} contract${event.markets.length === 1 ? '' : 's'} · ${fmtMoney(event.notional24h)} est. 24h</span>
      ${event.seriesUrl ? `<a class="event-link" href="${esc(event.seriesUrl)}" target="_blank" rel="noopener noreferrer">Kalshi ↗</a>` : ''}
    </td></tr>`);
    for (const m of event.markets.slice(0, 6)) {
      rows.push(renderMarketRow(m));
    }
  }
  $('marketRows').innerHTML = rows.join('');
  $('marketRows').querySelectorAll('tr[data-ticker]').forEach((tr) => {
    tr.onclick = () => selectMarket(tr.dataset.ticker);
  });
}

function renderMarketRow(m) {
  const selected = m.ticker === S.selected ? ' selected' : '';
  return `<tr data-ticker="${esc(m.ticker)}" class="${selected}">
    <td class="contract"><span class="tick">${esc(m.subtitle || m.title)}</span><span class="ticker">${esc(m.ticker)}</span></td>
    <td class="num" data-cell="bid">${cents(m.yesBid)}</td>
    <td class="num" data-cell="ask">${cents(m.yesAsk)}</td>
    <td class="num strong" data-cell="mid">${cents(m.mid)}</td>
    <td class="num" data-cell="vol">${fmtNum(m.volume24h)}</td>
    <td class="num">${fmtMoney(m.notional24h)}</td>
    <td class="num" data-cell="depth">${fmtNum(m.contractsWithin5c)}</td>
    <td><a href="${esc(m.apiUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">API ↗</a>
        ${m.seriesUrl ? `<a href="${esc(m.seriesUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">page ↗</a>` : ''}</td>
  </tr>`;
}

/* ------------------------------------------------------------------ selection + chart */

function selectMarket(ticker, force = false) {
  if (!force && S.selected === ticker) return;
  S.selected = ticker;
  const m = S.markets.get(ticker);
  if (m) {
    $('chartTitle').textContent = m.title;
    $('chartSub').innerHTML = `${esc(m.topic)} · <code>${esc(m.ticker)}</code> · closes ${esc(m.closeTime || '—')}`;
    $('chartMeta').innerHTML = `
      <span>Mid <b>${cents(m.mid)}</b></span>
      <span>Bid <b>${cents(m.yesBid)}</b> × ${fmtNum(m.bestBidSize)}</span>
      <span>Ask <b>${cents(m.yesAsk)}</b> × ${fmtNum(m.bestAskSize)}</span>
      <span>Spread <b>${m.spread == null ? '—' : cents(m.spread)}</b></span>
      <span>24h vol <b>${fmtNum(m.volume24h)}</b></span>
      <span>OI <b>${fmtNum(m.openInterest)}</b></span>`;
    loadBook(ticker);
  }
  document.querySelectorAll('#marketRows tr[data-ticker]').forEach((tr) =>
    tr.classList.toggle('selected', tr.dataset.ticker === ticker));
  loadSeries();
}

async function loadSeries() {
  if (!S.selected) return;
  try {
    const data = await getJSON(`/api/series?ticker=${encodeURIComponent(S.selected)}&seconds=${S.range}`);
    S.series = data.points || [];
    S.book = data.book || S.book;
    $('chartNote').textContent = S.series.length
      ? `${S.series.length} observation${S.series.length === 1 ? '' : 's'} in the selected window · each point is a server-side read, not an interpolation`
      : 'No observation in this window yet — the desk records one per tick.';
    drawChart();
    drawBook();
  } catch (err) {
    $('chartNote').textContent = 'Chart unavailable: ' + err.message;
  }
}

async function refreshSeries() {
  if (document.hidden) return;
  await loadSeries();
}

function drawChart() {
  const canvas = $('chartCanvas');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 700;
  const h = 280;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const padL = 44, padR = 14, padT = 14, padB = 26;
  const plotW = w - padL - padR, plotH = h - padT - padB;
  const now = Date.now();
  const start = now - S.range * 1000;
  const yFor = (p) => padT + (1 - p) * plotH;
  const xFor = (t) => padL + ((t - start) / (now - start)) * plotW;

  ctx.font = '11px ui-monospace, SFMono-Regular, Menlo, monospace';
  ctx.strokeStyle = 'rgba(255,255,255,.07)';
  ctx.fillStyle = 'rgba(255,255,255,.45)';
  for (const level of [0, 0.25, 0.5, 0.75, 1]) {
    const y = yFor(level);
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillText('$' + level.toFixed(2), 6, y + 4);
  }
  for (let i = 0; i <= 4; i += 1) {
    const t = start + ((now - start) * i) / 4;
    const x = xFor(t);
    ctx.strokeStyle = 'rgba(255,255,255,.04)';
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, h - padB);
    ctx.stroke();
    const label = S.range <= 60 ? new Date(t).toLocaleTimeString([], { hour12: false }) : '-' + Math.round((now - t) / 1000) + 's';
    ctx.fillStyle = 'rgba(255,255,255,.38)';
    ctx.fillText(label, Math.max(padL, Math.min(w - padR - 34, x - 16)), h - 8);
  }

  const pts = S.series.filter((p) => p.t * 1000 >= start).map((p) => ({ x: xFor(p.t * 1000), y: yFor(p.mid), mid: p.mid }));
  if (pts.length < 1) {
    ctx.fillStyle = 'rgba(255,255,255,.5)';
    ctx.font = '13px system-ui, sans-serif';
    ctx.fillText('No observations yet in this window.', padL + 12, padT + 30);
    return;
  }
  const last = pts[pts.length - 1];
  const colour = S.raw?.meta?.simulated ? '#ffc46b' : '#57dcae';

  const grad = ctx.createLinearGradient(0, padT, 0, h - padB);
  grad.addColorStop(0, 'rgba(87,220,174,.26)');
  grad.addColorStop(1, 'rgba(87,220,174,0)');
  ctx.beginPath();
  ctx.moveTo(pts[0].x, h - padB);
  for (const p of pts) ctx.lineTo(p.x, p.y);
  ctx.lineTo(last.x, h - padB);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.strokeStyle = colour;
  ctx.lineWidth = 1.8;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(last.x, last.y, 3.4, 0, Math.PI * 2);
  ctx.fillStyle = colour;
  ctx.fill();

  ctx.fillStyle = colour;
  ctx.font = '600 12px ui-monospace, monospace';
  ctx.fillText(cents(last.mid), Math.min(w - padR - 34, last.x + 6), Math.max(padT + 10, last.y - 8));
}

function drawEquity() {
  const canvas = $('equityCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 400;
  const h = 170;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const pts = S.equity.slice(-400);
  if (pts.length < 2) {
    ctx.fillStyle = 'rgba(255,255,255,.4)';
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillText('Equity curve builds as the book trades.', 12, 24);
    return;
  }
  const min = Math.min(...pts.map((p) => p.equity), 999);
  const max = Math.max(...pts.map((p) => p.equity), 1001);
  const span = Math.max(1, max - min);
  const xFor = (i) => 8 + (i / (pts.length - 1)) * (w - 16);
  const yFor = (v) => h - 12 - ((v - min) / span) * (h - 26);
  const rising = pts[pts.length - 1].equity >= pts[0].equity;
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(xFor(i), yFor(p.equity)) : ctx.moveTo(xFor(i), yFor(p.equity))));
  ctx.strokeStyle = rising ? '#57dcae' : '#ff8080';
  ctx.lineWidth = 1.6;
  ctx.stroke();
  ctx.fillStyle = 'rgba(255,255,255,.45)';
  ctx.font = '11px ui-monospace, monospace';
  ctx.fillText(fmtMoney(max, 2), 8, 12);
  ctx.fillText(fmtMoney(min, 2), 8, h - 2);
}

/* ------------------------------------------------------------------ book */

async function loadBook(ticker) {
  try {
    S.book = await getJSON('/api/book?ticker=' + encodeURIComponent(ticker));
    drawBook();
  } catch (err) {
    $('bookBody').innerHTML = `<p class="empty">Book unavailable: ${esc(err.message)}</p>`;
  }
}

function drawBook() {
  const book = S.book;
  if (!book || book.error) return;
  $('bookSource').href = book.docs || 'https://docs.kalshi.com/getting_started/orderbook_responses';
  const asks = (book.yesAsks || []).slice(0, 6).slice().reverse();
  const bids = (book.yesBids || []).slice(0, 6);
  const max = Math.max(1, ...asks.map((l) => l.contracts), ...bids.map((l) => l.contracts));
  const line = (lvl, side) => `
    <div class="book-row ${side}">
      <span class="px">${cents(lvl.price)}</span>
      <span class="bar"><i style="width:${Math.max(2, (lvl.contracts / max) * 100)}%"></i></span>
      <span class="qty">${fmtNum(lvl.contracts)}</span>
    </div>`;
  $('bookBody').innerHTML = `
    <div class="book-side">
      <div class="book-head"><span>YES ask</span><span>contracts</span></div>
      ${asks.map((l) => line(l, 'ask')).join('') || '<p class="empty">No ask side.</p>'}
    </div>
    <div class="spread-line">spread ${book.bestAsk != null ? cents(book.bestAsk - book.bestBid) : '—'} · ${fmtNum(book.contractsWithin5c)} contracts within 5¢ of the best bid</div>
    <div class="book-side">
      <div class="book-head"><span>YES bid</span><span>contracts</span></div>
      ${bids.map((l) => line(l, 'bid')).join('') || '<p class="empty">No bid side.</p>'}
    </div>`;
}

/* ------------------------------------------------------------------ feeds */

function alertCard(a, compact = false) {
  const dir = a.direction === 'up' ? '▲' : '▼';
  const search = 'https://www.google.com/search?q=' + encodeURIComponent((a.eventTitle || a.title || a.ticker) + ' news');
  return `<article class="alert ${a.direction} ${compact ? 'compact' : ''}">
    <div class="alert-top">
      <span class="dir ${a.direction}">${dir}</span>
      <span class="alert-price">${cents(a.from)} → <b>${cents(a.to)}</b></span>
      <span class="delta ${a.direction}">${a.direction === 'up' ? '+' : '−'}$${a.absDelta.toFixed(2)}</span>
      <time>${timeOf(a.at)}</time>
    </div>
    <div class="alert-title" title="${esc(a.title)}">${esc(a.title)}</div>
    <div class="alert-meta">
      <span class="chip topic">${esc(a.topic)}</span>
      <span class="chip score" title="Published six-component screen, not a forecast">score ${a.score}</span>
      <span class="dim">${fmtNum(a.contractsWithin5c)} within 5¢ · 24h ${fmtNum(a.volume24h)}</span>
    </div>
    <details class="why">
      <summary>Why it may have moved</summary>
      <p>No cause is asserted. Kalshi's own rule text is below; the search link is a search, not a finding.</p>
      <blockquote>${esc(a.rules || 'Rule text not captured for this contract.')}</blockquote>
      <p class="why-links">
        <a href="${esc(a.apiUrl)}" target="_blank" rel="noopener noreferrer">Kalshi API ↗</a>
        ${a.seriesUrl ? `<a href="${esc(a.seriesUrl)}" target="_blank" rel="noopener noreferrer">Market page ↗</a>` : ''}
        <a href="${search}" target="_blank" rel="noopener noreferrer">News search ↗</a>
      </p>
    </details>
  </article>`;
}

function renderFeeds() {
  const all = S.alertsAll.slice(0, 40);
  const model = S.alertsModel.slice(0, 40);
  $('allFeed').innerHTML = all.length ? all.map((a) => alertCard(a)).join('') : '<p class="empty">Waiting for the first $0.10 swing. At a 1s cadence that usually takes a few seconds in simulation.</p>';
  $('modelFeed').innerHTML = model.length ? model.map((a) => alertCard(a, true)).join('') : `<p class="empty">No move has scored 55 yet. The screen weights move size (30), resting depth (20), spread (20), 24h volume (20), distance from 50¢ (5) and freshness (5).</p>`;
  $('allCount').textContent = S.alertsAll.length;
  $('modelCount').textContent = S.alertsModel.length;
}

function pushAlert(a) {
  if (!a || !a.id) return;
  if (S.alertsAll.some((x) => x.id === a.id)) return;
  S.alertsAll.unshift(a);
  if (a.selected) S.alertsModel.unshift(a);
  S.alertsAll = S.alertsAll.slice(0, 120);
  S.alertsModel = S.alertsModel.slice(0, 120);
  const feed = $('allFeed');
  if (feed.querySelector('.empty')) feed.innerHTML = '';
  feed.insertAdjacentHTML('afterbegin', alertCard(a));
  while (feed.children.length > 40) feed.lastElementChild.remove();
  if (a.selected) {
    const mfeed = $('modelFeed');
    if (mfeed.querySelector('.empty')) mfeed.innerHTML = '';
    mfeed.insertAdjacentHTML('afterbegin', alertCard(a, true));
    while (mfeed.children.length > 40) mfeed.lastElementChild.remove();
  }
  $('allCount').textContent = S.alertsAll.length;
  $('modelCount').textContent = S.alertsModel.length;
}

/* ------------------------------------------------------------------ portfolio + analysis */

function renderPortfolio(folio) {
  if (!folio) return;
  $('folioStats').innerHTML = `
    <div><label>Equity</label><b class="${cls(folio.totalPnl)}">${fmtMoney(folio.equity, 2)}</b></div>
    <div><label>Cash</label><b>${fmtMoney(folio.cash, 2)}</b></div>
    <div><label>Realized</label><b class="${cls(folio.realized)}">${signed(folio.realized)}</b></div>
    <div><label>Unrealized</label><b class="${cls(folio.unrealized)}">${signed(folio.unrealized)}</b></div>
    <div><label>ROI</label><b class="${cls(folio.roiPct)}">${folio.roiPct >= 0 ? '+' : ''}${folio.roiPct}%</b></div>
    <div><label>Fees</label><b>${fmtMoney(folio.feesPaid, 2)}</b></div>`;
  const rows = folio.positions || [];
  $('positionRows').innerHTML = rows.length
    ? rows.map((p) => `<tr>
        <td><span class="chip strat">${esc(p.strategy)}</span></td>
        <td class="contract"><span class="tick">${esc(p.ticker)}</span><span class="ticker">${esc(p.side)} · ${esc(p.priceBand)}</span></td>
        <td class="num">${cents(p.entryPrice)}</td>
        <td class="num" data-cell="mark">${cents(p.mark)}</td>
        <td class="num ${cls(p.unrealized)}">${signed(p.unrealized)}</td>
        <td>${p.open ? 'open' : esc(p.exitReason)}</td>
      </tr>`).join('')
    : '<tr><td colspan="6" class="empty">No open positions. The strategies only open after a qualified swing.</td></tr>';
  S.equity = (folio.equityCurve || []).map((p) => ({ t: new Date(p.ts).getTime(), equity: p.equity }));
  drawEquity();
}

function renderAnalysis(folio) {
  if (!folio) return;
  const rows = folio[S.analysisGroup] || [];
  $('analysisRows').innerHTML = rows.length
    ? rows.map((r) => `<tr>
        <td><span class="chip strat">${esc(r.name)}</span></td>
        <td class="num">${r.trades}</td>
        <td class="num">${r.winRate == null ? '—' : r.winRate + '%'}</td>
        <td class="num ${cls(r.pnl)}">${signed(r.pnl)}</td>
        <td class="num ${cls(r.avgPnl)}">${signed(r.avgPnl)}</td>
        <td class="num">${r.avgHoldHours ?? '—'}</td>
      </tr>`).join('')
    : '<tr><td colspan="6" class="empty">No closed trades yet. Positions exit on take-profit, stop-loss or a time stop, so this fills within minutes of the first swing.</td></tr>';
}

function renderResolution(state) {
  const watch = state.resolvingSoon || [];
  $('watchRows').innerHTML = watch.length
    ? watch.slice(0, 12).map((r) => `<tr>
        <td class="contract"><span class="tick">${esc(r.title)}</span><span class="ticker">${esc(r.ticker)}</span></td>
        <td><span class="chip topic">${esc(r.topic)}</span></td>
        <td class="num">${formatCountdown(r.closesInSeconds)}</td>
        <td>${esc(r.status)}</td>
        <td>${r.result ? esc(r.result) : '<span class="dim">pending</span>'}</td>
      </tr>`).join('')
    : '<tr><td colspan="5" class="empty">No tracked contract has a close time in the capture.</td></tr>';
  const resolved = state.resolutions || [];
  $('resolvedCount').textContent = resolved.length;
  $('resolvedRows').innerHTML = resolved.length
    ? resolved.map((r) => `<tr>
        <td class="contract"><span class="tick">${esc(r.title)}</span><span class="ticker">${esc(r.ticker)}</span></td>
        <td>${esc(r.status)}</td>
        <td><b class="${r.result === 'yes' ? 'up' : r.result === 'no' ? 'down' : ''}">${esc(r.result)}</b></td>
        <td>${timeOf(r.recordedAt)}</td>
      </tr>`).join('')
    : '<tr><td colspan="4" class="empty">Nothing has finalised in the captured snapshot yet. The desk keeps polling; this table fills from Kalshi\'s own status field only.</td></tr>';
}

function formatCountdown(seconds) {
  if (seconds == null) return '—';
  if (seconds < 0) return 'closed';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

/* ------------------------------------------------------------------ stream */

function startStream() {
  const es = new EventSource('/api/stream');
  es.onopen = () => {
    S.connected = true;
    $('conn').className = 'conn ok';
  };
  es.onerror = () => {
    S.connected = false;
    $('conn').className = 'conn bad';
  };
  es.addEventListener('hello', (event) => {
    const data = JSON.parse(event.data);
    $('tickLine').textContent = `stream open · mode ${data.mode} · threshold ${(data.threshold * 100).toFixed(0)}¢`;
  });
  es.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (payload.type !== 'tick') return;
    applyTick(payload);
  };
}

function applyTick(tick) {
  for (const u of tick.updates || []) {
    const m = S.markets.get(u.ticker);
    if (!m) continue;
    m.mid = u.mid;
    m.yesBid = u.bid;
    m.yesAsk = u.ask;
    m.bestBidSize = u.bidSize;
    m.bestAskSize = u.askSize;
    m.spread = u.ask != null ? u.ask - u.bid : null;
    const tr = document.querySelector(`#marketRows tr[data-ticker="${CSS.escape(u.ticker)}"]`);
    if (tr) {
      tr.querySelector('[data-cell="bid"]').textContent = cents(u.bid);
      tr.querySelector('[data-cell="ask"]').textContent = cents(u.ask);
      tr.querySelector('[data-cell="mid"]').textContent = cents(u.mid);
    }
    if (u.ticker === S.selected) {
      S.series.push({ t: tick.ts, mid: u.mid });
      if (S.series.length > 5000) S.series = S.series.slice(-3000);
      drawChart();
      const meta = $('chartMeta').querySelector('b');
      if (meta) meta.textContent = cents(u.mid);
      if (S.book) {
        const ask = (S.book.yesAsks || [])[0];
        const bid = (S.book.yesBids || [])[0];
        if (ask) ask.price = u.ask;
        if (bid) bid.price = u.bid;
        if (ask) ask.contracts = u.askSize;
        if (bid) bid.contracts = u.bidSize;
        drawBook();
      }
    }
  }
  for (const a of tick.alerts || []) pushAlert(a);
  if (tick.equity != null) {
    S.equity.push({ t: tick.ts * 1000, equity: tick.equity });
    if (S.equity.length > 4000) S.equity = S.equity.slice(-2000);
    drawEquity();
    $('kpiEquity').textContent = fmtMoney(tick.equity, 2);
    $('kpiEquity').className = cls(tick.equity - 1000);
  }
  $('kpiAlerts').textContent = fmtNum(S.alertsAll.filter((a) => Date.now() - new Date(a.at).getTime() < 3600e3).length);
  const biggest = S.alertsAll.reduce((acc, a) => (!acc || a.absDelta > acc.absDelta ? a : acc), null);
  if (biggest) {
    $('kpiBiggest').textContent = '$' + biggest.absDelta.toFixed(2);
    $('kpiBiggestFoot').textContent = `${biggest.topic} · ${biggest.direction}`;
  }
  $('tickLine').textContent = `tick ${timeOf(tick.at)} · ${(tick.updates || []).length} quotes · mode ${tick.mode}`;
}

async function refreshState() {
  if (document.hidden) return;
  try {
    const state = await getJSON('/api/state');
    // Prices arrive by stream; here we only take the slower-moving bookkeeping.
    S.raw = state;
    renderPortfolio(state.portfolio);
    renderAnalysis(state.portfolio);
    renderResolution(state);
    renderKpis();
    if (!$('modeBadge').textContent || $('modeBadge').textContent === 'connecting') renderMeta();
  } catch {
    /* a failed refresh must not clear the dashboard */
  }
}

/* ------------------------------------------------------------------ UI wiring */

function bindUI() {
  $('ranges').querySelectorAll('button').forEach((btn) => {
    btn.onclick = () => {
      S.range = Number(btn.dataset.seconds);
      $('ranges').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
      loadSeries();
    };
  });
  $('analysisTabs').querySelectorAll('button').forEach((btn) => {
    btn.onclick = () => {
      S.analysisGroup = btn.dataset.group;
      $('analysisTabs').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
      renderAnalysis(S.raw?.portfolio);
    };
  });
  window.addEventListener('resize', () => {
    drawChart();
    drawEquity();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) loadSeries();
  });
}

boot();
