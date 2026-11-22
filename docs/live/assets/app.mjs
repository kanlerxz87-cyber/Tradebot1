// Live console client.
//
// Data comes from two places and is always labelled:
//   1. data/live.json  — a runner-side capture with a URL and read time on every row.
//   2. direct browser reads of the official demo hosts, used while the page is open so the console
//      is live rather than only as fresh as the last commit. Each browser read records its own
//      outcome; if the browser is blocked, the page keeps working from (1) and says so.
//
// No API key exists in this file, and no order endpoint is ever called.

import {
  num, quoteOf, bookOf, swing, triageScore, THRESHOLD, TOPICS, TOPIC_RULES,
  resolutionOf, settlementOf, portfolioSummary, RANGES, candleIntervalFor, withinRange,
  fmtCents, fmtDollars, fmtSigned, fmtQty, feeCents, contractsForYesAtMost, walkYesBuy,
} from './core.mjs';

const BASE = 'https://external-api.demo.kalshi.co/trade-api/v2';
const POLL_MS = 20_000;
const FEED_LIMIT = 60;
const SCORE_FLOOR = 55;

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');
const clockOf = (ms) => new Date(ms).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

const state = {
  capture: null,
  captureUrl: 'data/live.json',
  topic: 'all',
  rank: 'dollars',
  selected: null,
  range: RANGES[1],
  observations: new Map(), // ticker -> [{t, mark, basis, origin}]
  previous: new Map(), // ticker -> {mark, t}
  alerts: [],
  books: new Map(), // ticker -> book + provenance
  lastRead: null,
  origin: 'capture',
  browserOk: null,
  polling: true,
  timer: null,
  newSinceRender: 0,
  selfTest: [],
  candles: new Map(),
  portfolio: null,
};

/* ------------------------------------------------------------------ helpers */

function setStatus(message, kind = '') {
  const node = $('connection');
  node.textContent = message;
  node.className = `status ${kind}`;
}

function topicsEvents() {
  const events = state.capture?.events ?? [];
  if (state.topic === 'all') return events;
  return events.filter((event) => event.topic === state.topic);
}

function marketsOf(events) {
  return events.flatMap((event) => (event.markets ?? []).map((market) => ({ ...market, event })));
}

function dollarsOf(market) {
  const price = num(market.last_price_dollars);
  const volume = num(market.volume_24h_fp);
  // Derived only when both official fields exist; otherwise null, never zero.
  if (price === null || volume === null) return null;
  return price * volume;
}

function rankedMarkets() {
  const rows = marketsOf(topicsEvents()).filter((market) => (market.status ?? '') === 'active');
  const key = state.rank === 'volume' ? (m) => num(m.volume_24h_fp) : dollarsOf;
  return rows.sort((a, b) => {
    const av = key(a);
    const bv = key(b);
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv - av;
  });
}

function topicLabel(id) {
  if (id === 'all') return 'All topics';
  return TOPICS.find((topic) => topic.id === id)?.label ?? id;
}

/* ------------------------------------------------------------------ rendering */

function renderCounts() {
  const all = marketsOf(state.capture?.events ?? []);
  for (const id of ['all', ...TOPICS.map((topic) => topic.id)]) {
    const node = $(`count-${id}`);
    if (!node) continue;
    const count = id === 'all' ? all.length : all.filter((market) => market.topic === id).length;
    node.textContent = count.toLocaleString('en-US');
  }
}

function renderMetrics() {
  const rows = rankedMarkets();
  const events = new Set(rows.map((market) => market.event_ticker));
  const feed = visibleAlerts();
  $('stat-events').textContent = events.size.toLocaleString('en-US');
  $('stat-events-sub').textContent = topicLabel(state.topic);
  $('stat-markets').textContent = rows.length.toLocaleString('en-US');
  $('stat-alerts').textContent = feed.all.length.toLocaleString('en-US');
  $('stat-alerts-sub').textContent = state.origin === 'browser' ? 'this session, live reads' : 'this session';
  $('stat-books').textContent = Object.keys(state.capture?.books ?? {}).length.toLocaleString('en-US');
  $('stat-resolved').textContent = (state.capture?.resolutions ?? []).filter((row) => state.topic === 'all' || row.topic === state.topic).length.toLocaleString('en-US');
  const readAt = state.lastRead ?? state.capture?.generated_at ?? null;
  $('stat-updated').textContent = readAt ? timeOf(readAt) : '—';
  $('stat-source').textContent = state.origin === 'browser' ? 'this browser, live' : 'runner capture (static)';
}

function renderTable() {
  const rows = rankedMarkets().slice(0, 120);
  const target = $('market-rows');
  if (!rows.length) {
    target.innerHTML = '<tr><td colspan="7" class="empty">No verified market in this topic yet. A blank is not a zero.</td></tr>';
    return;
  }
  target.innerHTML = rows
    .map((market) => {
      const quote = quoteOf(market);
      const topic = market.topic;
      const resolution = resolutionOf(market);
      const dollars = dollarsOf(market);
      const selected = market.ticker === state.selected ? ' class="selected"' : '';
      return `<tr${selected}>
        <td>
          <span class="topic-tag ${esc(topic)}">${esc(topic)}</span>
          <button class="market-link" type="button" data-select="${esc(market.ticker)}">${esc(market.event?.title ?? market.title ?? market.ticker)}</button>
          <span class="sub">${esc(market.title ?? '')} &middot; <span class="mono">${esc(market.ticker)}</span></span>
        </td>
        <td class="num">${fmtCents(quote.mark)}<span class="sub">${esc(quote.basis)}</span></td>
        <td class="num">${fmtCents(quote.yesBid)} / ${fmtCents(quote.yesAsk)}${quote.spread === null ? '<span class="sub">one-sided</span>' : `<span class="sub">${fmtCents(quote.spread)} wide</span>`}</td>
        <td class="num">${fmtQty(num(market.volume_24h_fp))}</td>
        <td class="num">${dollars === null ? '—' : fmtDollars(dollars)}</td>
        <td>${esc(resolution.label)}</td>
        <td><a href="https://kalshi.com/markets/${esc((market.series_ticker ?? '').toLowerCase())}" target="_blank" rel="noopener noreferrer">Kalshi &#8599;</a><span class="sub"><a href="${esc(market.source_url ?? '#')}" target="_blank" rel="noopener noreferrer">API read</a></span></td>
      </tr>`;
    })
    .join('');
  target.querySelectorAll('[data-select]').forEach((button) => {
    button.addEventListener('click', () => select(button.dataset.select));
  });
}

function renderSelected() {
  const ticker = state.selected;
  $('selected-ticker').textContent = ticker ?? 'none selected';
  const body = $('selected-body');
  if (!ticker) {
    body.innerHTML = '<p class="empty">Pick a market in the table to chart it and to see its book.</p>';
    return;
  }
  const market = marketsOf(state.capture?.events ?? []).find((row) => row.ticker === ticker);
  if (!market) {
    body.innerHTML = '<p class="empty">That market is no longer in the current capture.</p>';
    return;
  }
  const quote = quoteOf(market);
  const resolution = resolutionOf(market);
  const levels = state.books.get(ticker);
  const fill = levels ? walkYesBuy(levels, 50) : null;
  const fee50 = quote.yesAsk === null ? null : feeCents(quote.yesAsk, 50);
  const sources = (market.event?.settlement_sources ?? []).slice(0, 3);
  body.innerHTML = `
    <h3>${esc(market.title ?? ticker)}</h3>
    <p class="hint">${esc(market.event?.title ?? '')} &middot; closes ${esc(market.close_time ?? '—')}</p>
    <dl class="kv">
      <dt>Mark</dt><dd>${fmtCents(quote.mark)} (${esc(quote.basis)})</dd>
      <dt>YES bid</dt><dd>${fmtCents(quote.yesBid)} &times; ${fmtQty(num(market.yes_bid_size_fp))}</dd>
      <dt>YES ask</dt><dd>${fmtCents(quote.yesAsk)} &times; ${fmtQty(num(market.yes_ask_size_fp))}</dd>
      <dt>Spread</dt><dd>${quote.spread === null ? 'one-sided' : fmtCents(quote.spread)}</dd>
      <dt>Last trade</dt><dd>${fmtCents(quote.last)}</dd>
      <dt>Contracts to pay &le; ${fmtCents(quote.yesAsk)}</dt><dd>${levels ? fmtQty(contractsForYesAtMost(levels, quote.yesAsk)) : 'book not loaded'}</dd>
      <dt>50 contracts, walked</dt><dd>${fill ? `${fill.complete ? fmtCents(fill.averagePrice) : `${fmtQty(fill.filled)} of 50`}` : '—'}</dd>
      <dt>Taker fee, 50 @ ask</dt><dd>${fee50 === null ? '—' : `$${fee50.toFixed(6)}`}</dd>
      <dt>Status</dt><dd>${esc(market.status ?? '—')}</dd>
      <dt>Result</dt><dd>${esc(resolution.result ?? 'not resolved')}</dd>
    </dl>
    ${sources.length ? `<p class="hint" style="margin-top:8px">Kalshi's stated settlement sources: ${sources.map((source) => `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.name)}</a>`).join(', ')}</p>` : ''}
    <p class="hint">Book read: ${levels ? esc(timeOf(levels.read_at)) : 'not in this capture'} &middot; <a href="${esc(market.source_url ?? '#')}" target="_blank" rel="noopener noreferrer">exact request</a></p>`;
}

function renderBook() {
  const ticker = state.selected;
  const levels = state.books.get(ticker);
  const node = $('book-rows');
  if (!ticker) {
    node.innerHTML = '<p class="empty">Select a market to see the contracts resting at each price.</p>';
    return;
  }
  if (!levels) {
    node.innerHTML = '<p class="empty">No order-book read for this market in the current capture. Books are fetched for the highest-dollar markets only.</p>';
    return;
  }
  if (levels.empty) {
    node.innerHTML = '<p class="empty">The API returned an empty book for this market. An empty book is not a price of zero (S5).</p>';
    return;
  }
  const max = Math.max(...[...levels.yes, ...levels.no].map((level) => level.qty), 1);
  const row = (level, side) => `<tr>
      <td class="mono">${fmtCents(level.price)}</td>
      <td class="num">${fmtQty(level.qty)}</td>
      <td><div class="bar"><span style="width:${Math.max(2, (level.qty / max) * 100).toFixed(1)}%;background:${side === 'yes' ? '#3ddc97' : '#ff6b6b'}"></span></div></td>
    </tr>`;
  node.innerHTML = `<table>
      <tbody>
        <tr class="side-head"><td colspan="3">YES bids &middot; ${fmtQty(levels.yes.reduce((total, l) => total + l.qty, 0))} contracts</td></tr>
        ${levels.yes.slice(0, 8).map((level) => row(level, 'yes')).join('') || '<tr><td colspan="3" class="empty">no YES bids</td></tr>'}
        <tr class="side-head"><td colspan="3">NO bids &middot; buying these fills a YES ask at 100&cent; minus the price</td></tr>
        ${levels.no.slice(0, 8).map((level) => row(level, 'no')).join('') || '<tr><td colspan="3" class="empty">no NO bids</td></tr>'}
        <tr class="side-head"><td colspan="3">Implied YES ask ${fmtCents(levels.yesAsk)} &middot; spread ${levels.spread === null ? 'one-sided' : fmtCents(levels.spread)}</td></tr>
      </tbody>
    </table>
    <p class="hint" style="padding:8px 10px">Read ${esc(timeOf(levels.read_at))} &middot; <a href="${esc(levels.source_url)}" target="_blank" rel="noopener noreferrer">exact request</a>. Kalshi returns bids only; the ask is implied by the best opposite bid (S4).</p>`;
}

function visibleAlerts() {
  const list = state.alerts.filter((alert) => state.topic === 'all' || alert.topic === state.topic);
  return { all: list, screened: list.filter((alert) => alert.screen) };
}

function renderFeeds() {
  const feed = visibleAlerts();
  $('feed-all-count').textContent = `${feed.all.length} shown`;
  $('feed-screen-count').textContent = `${feed.screened.length} shown`;
  const item = (alert) => `<article class="feed-item">
      <div class="feed-top">
        <span class="${alert.delta > 0 ? 'up' : 'down'}">${alert.delta > 0 ? '&#8599;' : '&#8600;'} ${fmtSigned(alert.delta)} &nbsp;${fmtCents(alert.from)} &rarr; ${fmtCents(alert.to)}</span>
        <time>${clockOf(alert.at)}</time>
      </div>
      <strong>${esc(alert.title)}</strong>
      <span class="meta"><span class="topic-tag ${esc(alert.topic)}">${esc(alert.topic)}</span> ${esc(alert.ticker)} &middot; score <span class="score">${alert.score}</span> &middot; ${esc(alert.basis)} basis &middot; ${esc(alert.origin)} read</span>
      <span class="meta">${alert.liquidity === null ? 'liquidity: no book read' : `contracts at touch: ${fmtQty(alert.liquidity)}`} &middot; spread ${alert.spread === null ? 'one-sided' : fmtCents(alert.spread)}</span>
      <a href="https://kalshi.com/markets/${esc((alert.seriesTicker ?? '').toLowerCase())}" target="_blank" rel="noopener noreferrer">Kalshi market page &#8599;</a>
      &middot; <a href="${esc(alert.sourceUrl ?? '#')}" target="_blank" rel="noopener noreferrer">API read &#8599;</a>
      <span class="meta">Cause: not attributed. No official article has been matched to this move.</span>
    </article>`;
  const fill = (node, list, emptyText) => {
    node.innerHTML = list.length
      ? list.slice(0, FEED_LIMIT).map(item).join('')
      : `<p class="feed-empty">${emptyText}</p>`;
  };
  fill($('all-feed'), feed.all, 'No swing has been observed yet. The feed stays empty rather than showing a move that was not measured.');
  fill($('screen-feed'), feed.screened, `No swing has cleared the triage floor of ${SCORE_FLOOR} yet. The rule is published on the Verification page.`);
}

function renderResolutions() {
  const rows = (state.capture?.resolutions ?? []).filter((row) => state.topic === 'all' || row.topic === state.topic);
  $('resolution-count').textContent = `${rows.length} on file`;
  const target = $('resolved-rows');
  if (!rows.length) {
    target.innerHTML = '<tr><td colspan="5" class="empty">No resolved market on file for this topic yet. The tracker stays empty until the API reports result = yes or no.</td></tr>';
    return;
  }
  target.innerHTML = rows
    .slice(0, 80)
    .map(
      (row) => `<tr>
      <td>${esc(row.event_title ?? row.event_ticker)}<span class="sub">${esc(row.event_ticker)}</span></td>
      <td>${esc(row.market_title ?? '')}<span class="sub mono">${esc(row.ticker)}</span></td>
      <td class="${row.result === 'yes' ? 'up' : 'down'}">${esc(row.result.toUpperCase())}</td>
      <td>${esc(row.settlement_ts ?? '—')}<span class="sub">${esc(row.status ?? '')}</span></td>
      <td><a href="${esc(row.source_url)}" target="_blank" rel="noopener noreferrer">API read</a></td>
    </tr>`,
    )
    .join('');
}

function renderPortfolio() {
  const ledger = state.capture?.portfolio;
  const body = $('paper-rows');
  if (!ledger) {
    body.innerHTML = '<p class="empty">No simulated ledger in this capture.</p>';
    return;
  }
  const marks = {};
  for (const market of marketsOf(state.capture?.events ?? [])) marks[market.ticker] = quoteOf(market).mark;
  const summary = portfolioSummary(ledger, marks);
  const byStrategy = new Map();
  for (const position of ledger.positions ?? []) {
    const key = position.strategy ?? 'untagged';
    const bucket = byStrategy.get(key) ?? { open: 0, contracts: 0, entry: 0 };
    bucket.open += 1;
    bucket.contracts += num(position.contracts) ?? 0;
    bucket.entry += (num(position.contracts) ?? 0) * (num(position.entryPrice) ?? 0);
    byStrategy.set(key, bucket);
  }
  const resolvedPositions = (ledger.fills ?? []).filter((fill) => fill.realised !== undefined && fill.realised !== null);
  const realised = resolvedPositions.reduce((total, fill) => total + (num(fill.realised) ?? 0), 0);
  body.innerHTML = `
    <dl class="kv">
      <dt>Cash</dt><dd>${fmtDollars(summary.cash)}</dd>
      <dt>Open positions at mark</dt><dd>${fmtDollars(summary.openValue)}</dd>
      <dt>Equity</dt><dd>${fmtDollars(summary.equity)}</dd>
      <dt>Realised on settled paper positions</dt><dd>${fmtDollars(realised)}</dd>
      <dt>Fees paid</dt><dd>${fmtDollars(summary.fees)}</dd>
      <dt>Unpriced positions</dt><dd>${summary.unpricedPositions}</dd>
    </dl>
    <p class="hint" style="margin-top:8px">
      ${ledger.note ? esc(ledger.note) : 'Paper accounting only; the page cannot place an order.'}
      ${ledger.reconcile ? `<br>${esc(ledger.reconcile)}` : ''}
    </p>
    ${byStrategy.size ? `<table style="margin-top:8px"><thead><tr><th>Strategy</th><th class="num">Open</th><th class="num">Contracts</th><th class="num">Cost</th></tr></thead><tbody>${[...byStrategy.entries()].map(([name, bucket]) => `<tr><td>${esc(name)}</td><td class="num">${bucket.open}</td><td class="num">${fmtQty(bucket.contracts)}</td><td class="num">${fmtDollars(bucket.entry)}</td></tr>`).join('')}</tbody></table>` : ''}`;
}

/* -------------------------------------------------------------------- chart */

const CHART = { padLeft: 46, padRight: 12, padTop: 12, padBottom: 26 };

function chartPoints() {
  const ticker = state.selected;
  if (!ticker) return { marks: [], swings: [] };
  const now = Date.now();
  const marks = [];
  for (const series of [state.observations.get(ticker) ?? [], state.candles.get(ticker) ?? []]) {
    for (const point of series) marks.push(point);
  }
  const ordered = withinRange(marks, now, state.range.ms);
  return {
    marks: ordered,
    swings: state.alerts.filter((alert) => alert.ticker === ticker && alert.at >= now - state.range.ms),
  };
}

function drawChart() {
  const canvas = $('chart');
  if (!canvas) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 600;
  const height = 300;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const plot = { x: CHART.padLeft, y: CHART.padTop, w: width - CHART.padLeft - CHART.padRight, h: height - CHART.padTop - CHART.padBottom };
  // y axis is a fixed 0c-100c contract price grid so two charts read the same way.
  const yOf = (price) => plot.y + plot.h - (price / 1) * plot.h;
  const now = Date.now();
  const from = now - state.range.ms;
  const xOf = (time) => plot.x + ((time - from) / state.range.ms) * plot.w;

  ctx.strokeStyle = '#162d3a';
  ctx.fillStyle = '#8ba3b1';
  ctx.font = '11px ui-monospace, Menlo, monospace';
  ctx.lineWidth = 1;
  for (let cents = 0; cents <= 100; cents += 20) {
    const y = yOf(cents / 100);
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    ctx.fillText(`${cents}¢`, 8, y + 4);
  }
  const tickCount = 5;
  for (let index = 0; index <= tickCount; index += 1) {
    const time = from + (state.range.ms * index) / tickCount;
    const x = xOf(time);
    ctx.beginPath();
    ctx.moveTo(x, plot.y);
    ctx.lineTo(x, plot.y + plot.h);
    ctx.stroke();
    const label = state.range.ms <= 3_600_000
      ? new Date(time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : new Date(time).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    ctx.fillText(label, Math.min(x, plot.x + plot.w - 58), height - 8);
  }

  const { marks, swings } = chartPoints();
  $('chart-scale').textContent = `0–100¢ · ${state.range.label}`;
  if (!state.selected) {
    ctx.fillStyle = '#8ba3b1';
    ctx.font = '13px -apple-system, sans-serif';
    ctx.fillText('Select a market to draw its price path.', plot.x + 12, plot.y + 24);
    return;
  }
  if (!marks.length) {
    ctx.fillStyle = '#ffc857';
    ctx.font = '13px -apple-system, sans-serif';
    ctx.fillText('No observation inside this range yet. Points appear as the page polls.', plot.x + 12, plot.y + 24);
    return;
  }
  ctx.strokeStyle = '#4cc9f0';
  ctx.lineWidth = 2;
  ctx.beginPath();
  marks.forEach((point, index) => {
    const x = xOf(point.t);
    const y = yOf(Math.min(1, Math.max(0, point.mark)));
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#4cc9f0';
  for (const point of marks) {
    ctx.beginPath();
    ctx.arc(xOf(point.t), yOf(Math.min(1, Math.max(0, point.mark))), 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
  for (const alert of swings) {
    const x = xOf(alert.at);
    const y = yOf(Math.min(1, Math.max(0, alert.to)));
    ctx.fillStyle = '#ffc857';
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#0b1a23';
    ctx.font = 'bold 9px ui-monospace, monospace';
    ctx.fillText(alert.delta > 0 ? '+' : '−', x - 3, y + 3);
  }
  canvas.dataset.points = String(marks.length);
  canvas.dataset.swings = String(swings.length);
}

function renderChart() {
  drawChart();
  const note = $('chart-note');
  const interval = candleIntervalFor(state.range.ms);
  note.textContent = state.selected
    ? `Line: marks this page observed (${POLL_MS / 1000}s poll). Candlesticks: official endpoint, ${interval}-minute interval (S6). Swings are drawn where two observations differed by at least ${fmtCents(THRESHOLD)}.`
    : 'The page polls the public REST API while it is open, so the line starts when you arrive. Candlesticks come from the official endpoint.';
}

/* ------------------------------------------------------------------ data load */

async function loadCapture() {
  for (const candidate of ['data/live.json', '../live/data/live.json']) {
    try {
      const response = await fetch(candidate, { cache: 'no-store' });
      if (!response.ok) continue;
      const data = await response.json();
      state.capture = data;
      state.captureUrl = candidate;
      state.books = new Map(Object.entries(data.books ?? {}).map(([ticker, book]) => [ticker, { ...book, empty: !book.yes?.length && !book.no?.length }]));
      state.lastRead = data.generated_at ?? null;
      return true;
    } catch {
      /* try the next path */
    }
  }
  return false;
}

function absorbEvents(events, origin, readAt) {
  let changed = 0;
  for (const event of events) {
    for (const market of event.markets ?? []) {
      const quote = quoteOf(market);
      if (quote.mark === null) continue;
      const ticker = market.ticker;
      const series = state.observations.get(ticker) ?? [];
      const last = series[series.length - 1];
      const at = Date.parse(readAt) || Date.now();
      if (!last || last.mark !== quote.mark) {
        series.push({ t: at, mark: quote.mark, basis: quote.basis });
        state.observations.set(ticker, series.slice(-2000));
      }
      const before = state.previous.get(ticker);
      if (before) {
        const move = swing(before.mark, quote.mark);
        if (move) {
          const book = state.books.get(ticker);
          const liquidity = book ? (quote.yesAsk !== null ? contractsForYesAtMost(book, quote.yesAsk) : null) : null;
          const volume = num(market.volume_24h_fp);
          const score = triageScore({ moveAbs: move.delta, sizeAtTouch: liquidity, spread: quote.spread, volume24h: volume });
          const alert = {
            at,
            ticker,
            seriesTicker: market.series_ticker,
            title: market.title ?? event.title ?? ticker,
            topic: market.topic,
            delta: move.delta,
            from: before.mark,
            to: quote.mark,
            basis: quote.basis,
            origin,
            sourceUrl: market.source_url,
            liquidity,
            spread: quote.spread,
            score: score.score,
            screen: score.score >= SCORE_FLOOR,
          };
          const duplicate = state.alerts.find((existing) => existing.ticker === ticker && Math.abs(existing.at - at) < 1500 && Math.abs(existing.delta - move.delta) < 1e-9);
          if (!duplicate) {
            state.alerts.unshift(alert);
            state.alerts = state.alerts.slice(0, 400);
            changed += 1;
            state.newSinceRender += 1;
          }
        }
      }
      // S21: previous_* fields describe a day ago, so they are never used to seed the baseline.
      state.previous.set(ticker, { mark: quote.mark, at, origin });
    }
  }
  return changed;
}

async function pollBrowser() {
  if (!state.polling) return;
  const button = $('refresh');
  button.disabled = true;
  try {
    const response = await fetch(`${BASE}/events?status=open&with_nested_markets=true&limit=200`, { cache: 'no-store', signal: AbortSignal.timeout(15_000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const readAt = new Date().toISOString();
    const keep = new Set((state.capture?.topics ?? []).flatMap((topic) => (topic.series ?? []).map((series) => series.ticker)));
    const events = (data.events ?? [])
      .filter((event) => keep.has(event.series_ticker))
      .map((event) => ({
        ...event,
        topic: (state.capture?.topics ?? []).find((topic) => (topic.series ?? []).some((series) => series.ticker === event.series_ticker))?.topic,
        markets: (event.markets ?? []).map((market) => ({ ...market, series_ticker: event.series_ticker, source_url: `${BASE}/events?status=open&with_nested_markets=true&limit=200` })),
      }));
    // Keep the capture's own market rows too, so a topic the demo catalogue drops does not vanish.
    const merged = new Map((state.capture?.events ?? []).map((event) => [event.event_ticker, event]));
    for (const event of events) merged.set(event.event_ticker, { ...(merged.get(event.event_ticker) ?? {}), ...event });
    state.capture = { ...state.capture, events: [...merged.values()] };
    const moved = absorbEvents(events, 'browser', readAt);
    state.lastRead = readAt;
    state.origin = 'browser';
    state.browserOk = true;
    setStatus(`Live · ${moved} new swing${moved === 1 ? '' : 's'} · ${timeOf(readAt)}`, 'ok');
    renderAll();
  } catch (error) {
    state.browserOk = false;
    setStatus(`Browser blocked (${error.message}); showing runner capture`, 'pending');
  } finally {
    button.disabled = false;
    if (state.polling) {
      clearTimeout(state.timer);
      state.timer = setTimeout(pollBrowser, POLL_MS);
    }
  }
}

async function loadCandles() {
  const ticker = state.selected;
  if (!ticker) return;
  const market = marketsOf(state.capture?.events ?? []).find((row) => row.ticker === ticker);
  if (!market?.series_ticker) return;
  const end = Math.floor(Date.now() / 1000);
  const interval = candleIntervalFor(state.range.ms);
  const span = Math.max(3600, Math.ceil(state.range.ms / 1000));
  const url = `${BASE}/series/${encodeURIComponent(market.series_ticker)}/markets/${encodeURIComponent(ticker)}/candlesticks?start_ts=${end - span}&end_ts=${end}&period_interval=${interval}`;
  try {
    const response = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(15_000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const points = (data.candlesticks ?? [])
      .map((candle) => {
        const close = num(candle?.price?.close_dollars) ?? num(candle?.yes_bid?.close_dollars);
        return close === null ? null : { t: Number(candle.end_period_ts) * 1000, mark: close, basis: `candle ${interval}m` };
      })
      .filter(Boolean);
    state.candles.set(ticker, points);
    $('chart-note').dataset.candles = `${points.length} candles`;
    renderChart();
  } catch (error) {
    $('chart-note').dataset.candles = `candlesticks unavailable (${error.message})`;
    renderChart();
  }
}

async function select(ticker) {
  state.selected = ticker;
  renderTable();
  renderSelected();
  renderBook();
  if (!state.books.has(ticker)) {
    try {
      const response = await fetch(`${BASE}/markets/${encodeURIComponent(ticker)}/orderbook?depth=10`, { cache: 'no-store', signal: AbortSignal.timeout(12_000) });
      if (response.ok) {
        const data = await response.json();
        const book = bookOf(data.orderbook_fp);
        state.books.set(ticker, { ...book, read_at: new Date().toISOString(), source_url: `${BASE}/markets/${encodeURIComponent(ticker)}/orderbook?depth=10` });
        renderBook();
        renderSelected();
      }
    } catch {
      /* the capture's books remain the fallback */
    }
  }
  await loadCandles();
  renderChart();
}

/* ----------------------------------------------------------------- self-test */

async function selfTest() {
  const rows = [];
  const add = (name, status, detail) => rows.push({ name, status, detail });
  const started = performance.now();
  try {
    const response = await fetch(`${BASE}/exchange/status`, { cache: 'no-store', signal: AbortSignal.timeout(10_000) });
    const body = await response.json().catch(() => null);
    add('GET /exchange/status', response.ok ? 'ok' : 'failed', `${response.status} · ${Math.round(performance.now() - started)}ms · trading_active=${body?.trading_active ?? '—'}`);
    state.browserOk = response.ok;
  } catch (error) {
    add('GET /exchange/status', 'blocked', error.message);
    state.browserOk = false;
  }
  try {
    const response = await fetch(`${BASE}/markets?limit=1&status=open`, { cache: 'no-store', signal: AbortSignal.timeout(10_000) });
    add('GET /markets (CORS read)', response.ok ? 'ok' : 'failed', `HTTP ${response.status}`);
  } catch (error) {
    add('GET /markets (CORS read)', 'blocked', `${error.message} — the page falls back to the runner capture`);
  }
  const ws = await new Promise((resolve) => {
    let socket;
    const done = (value) => {
      try { socket?.close(); } catch { /* already closed */ }
      resolve(value);
    };
    try {
      socket = new WebSocket('wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2');
    } catch (error) {
      resolve(`constructor error: ${error.message}`);
      return;
    }
    const timer = setTimeout(() => done('no close event within 6s'), 6000);
    socket.onopen = () => { clearTimeout(timer); done('opened without credentials (unexpected)'); };
    socket.onerror = () => { /* browsers hide details; the close event carries the code */ };
    socket.onclose = (event) => { clearTimeout(timer); done(`closed code ${event.code}${event.reason ? ` · ${event.reason}` : ''}`); };
  });
  add('WebSocket handshake, no credentials', 'measured', ws);
  add('Order placement', 'not attempted', 'this page holds no API key and never calls an order endpoint');
  state.selfTest = rows;
  $('selftest-body').innerHTML = `<table><thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead><tbody>${rows
    .map((row) => `<tr><td>${esc(row.name)}</td><td class="${row.status === 'ok' ? 'up' : row.status === 'blocked' || row.status === 'failed' ? 'down' : 'warn'}">${esc(row.status)}</td><td class="mono">${esc(row.detail)}</td></tr>`)
    .join('')}</tbody></table>
    <p class="hint" style="margin-top:8px">Measured ${esc(new Date().toLocaleTimeString('en-US'))} from this browser. A WS close code of 1006 without a reason is what a browser reports for a rejected unauthenticated handshake (S10, S24); it is not proof of a successful connection.</p>`;
}

/* -------------------------------------------------------------------- wiring */

function renderAll() {
  renderCounts();
  renderMetrics();
  renderTable();
  renderSelected();
  renderBook();
  renderFeeds();
  renderResolutions();
  renderPortfolio();
  renderChart();
}

function setTopic(topic) {
  state.topic = topic;
  document.querySelectorAll('[data-topic-link]').forEach((link) => {
    link.classList.toggle('active', link.dataset.topicLink === topic);
  });
  $('crumb').textContent = `/ ${topicLabel(topic)}`;
  renderAll();
}

function buildRanges() {
  const node = $('ranges');
  node.innerHTML = RANGES.map((range) => `<button class="range${range.id === state.range.id ? ' active' : ''}" type="button" data-range="${range.id}">${esc(range.label)}</button>`).join('');
  node.querySelectorAll('[data-range]').forEach((button) => {
    button.addEventListener('click', async () => {
      state.range = RANGES.find((range) => range.id === button.dataset.range) ?? RANGES[1];
      node.querySelectorAll('[data-range]').forEach((other) => other.classList.toggle('active', other === button));
      await loadCandles();
      renderChart();
    });
  });
}

async function boot() {
  buildRanges();
  const loaded = await loadCapture();
  if (loaded) {
    state.origin = 'capture';
    absorbEvents(state.capture.events ?? [], 'capture', state.capture.generated_at ?? new Date().toISOString());
    const fresh = state.capture.generated_at ? Date.parse(state.capture.generated_at) : null;
    const age = fresh ? Math.round((Date.now() - fresh) / 60000) : null;
    setStatus(fresh ? `Static capture, ${age}m old` : 'Static capture', age !== null && age > 180 ? 'pending' : 'ok');
  } else {
    setStatus('No runner capture found; live reads only', 'pending');
  }
  state.books = new Map(Object.entries(state.capture?.books ?? {}).map(([ticker, book]) => [ticker, { ...book, empty: !(book.yes?.length || book.no?.length) }]));

  document.querySelectorAll('[data-topic-link]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      setTopic(link.dataset.topicLink);
    });
  });
  document.querySelectorAll('[data-rank]').forEach((button) => {
    button.addEventListener('click', () => {
      state.rank = button.dataset.rank;
      document.querySelectorAll('[data-rank]').forEach((other) => other.classList.toggle('active', other === button));
      $('rank-note').textContent = state.rank === 'dollars' ? 'rank = last price × 24h contracts' : 'rank = 24h contracts';
      renderTable();
      renderMetrics();
    });
  });
  $('refresh').addEventListener('click', () => {
    clearTimeout(state.timer);
    pollBrowser();
  });
  $('autopoll').addEventListener('click', (event) => {
    state.polling = !state.polling;
    event.currentTarget.textContent = `Auto-refresh: ${state.polling ? 'on' : 'off'}`;
    event.currentTarget.setAttribute('aria-pressed', String(state.polling));
    if (state.polling) pollBrowser();
    else clearTimeout(state.timer);
  });
  $('selftest').addEventListener('click', selfTest);
  window.addEventListener('resize', () => drawChart());
  const canvas = $('chart');
  canvas.addEventListener('mousemove', (event) => {
    const tip = $('chart-tip');
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const now = Date.now();
    const from = now - state.range.ms;
    const time = from + ((x - CHART.padLeft) / Math.max(1, rect.width - CHART.padLeft - CHART.padRight)) * state.range.ms;
    const { marks } = chartPoints();
    let nearest = null;
    for (const point of marks) if (!nearest || Math.abs(point.t - time) < Math.abs(nearest.t - time)) nearest = point;
    if (!nearest || Math.abs(nearest.t - time) > state.range.ms / 12) {
      tip.style.display = 'none';
      return;
    }
    tip.style.display = 'block';
    tip.style.left = `${Math.min(rect.width - 150, x + 12)}px`;
    tip.style.top = '14px';
    tip.innerHTML = `${fmtCents(nearest.mark)}<br>${clockOf(nearest.t)}<br><span style="color:#8ba3b1">${esc(nearest.basis ?? '')}</span>`;
  });
  canvas.addEventListener('mouseleave', () => { $('chart-tip').style.display = 'none'; });

  renderAll();
  selfTest();
  if (state.polling) pollBrowser();
}

boot();
