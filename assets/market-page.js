// market.html?t=<ticker>
//
// Everything on this page is either an exchange field (labelled with its source
// URL) or a value this page derives and says so. A missing field renders as a
// dash, never as zero.

import {
  loadLocal, probeApi, renderBanner, money, cents, num, int, esc, dash, stamp, timeAgo, sourceLink,
  DEMO_REST, TOPIC_LABELS,
} from './common.js';
import { drawChart, WINDOWS, bucketSeries } from './chart.js';

const params = new URLSearchParams(location.search);
const ticker = params.get('t') ?? '';

const el = Object.fromEntries([
  'data-banner', 'm-title', 'm-topic', 'm-ticker', 'm-status', 'm-result', 'm-rules', 'crumb',
  'm-bid', 'm-ask', 'm-spread', 'm-volume', 'ladder-yes', 'ladder-ask', 'depth-bid', 'depth-ask',
  'm-oi', 'res-table', 'm-details', 'chart', 'chart-note', 'pt-out', 'pt-price', 'pt-count', 'pt-side', 'pt-run',
].map((id) => [id, document.getElementById(id)]));

const state = {
  market: null,
  book: null,
  history: [],
  alerts: [],
  resolution: null,
  window: '1h',
  source: 'snapshot',
};

const n = (v) => (v === null || v === undefined || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : null));

function setText(node, value) { if (node) node.textContent = value; }

async function loadSnapshotMarket() {
  const snap = await loadLocal('data/snapshot.json');
  const market = (snap.markets ?? []).find((m) => m.ticker === ticker);
  if (!market) return false;
  state.market = { ...market, observedAt: snap.meta?.capturedAt ?? null };
  state.source = 'snapshot';
  if (market.orderbook?.raw) {
    try {
      const ob = JSON.parse(market.orderbook.raw).orderbook_fp ?? {};
      state.book = { yes: (ob.yes_dollars ?? []).map(([p, q]) => [Number(p), Number(q)]), no: (ob.no_dollars ?? []).map(([p, q]) => [Number(p), Number(q)]), sourceUrl: market.orderbook.sourceUrl };
    } catch { state.book = null; }
  }
  return true;
}

async function loadLiveMarket() {
  const probe = await probeApi();
  if (!probe.ok) return false;
  try {
    const [mRes, bRes] = await Promise.all([
      fetch(`${DEMO_REST}/markets/${encodeURIComponent(ticker)}`),
      fetch(`${DEMO_REST}/markets/${encodeURIComponent(ticker)}/orderbook`),
    ]);
    if (!mRes.ok) return false;
    const m = (await mRes.json()).market;
    const b = bRes.ok ? (await bRes.json()).orderbook_fp : null;
    state.market = {
      ticker: m.ticker, eventTicker: m.event_ticker, seriesTicker: (m.event_ticker ?? '').split('-')[0],
      title: m.title, status: m.status, result: m.result,
      yesBid: n(m.yes_bid_dollars), yesAsk: n(m.yes_ask_dollars),
      volume: n(m.volume_fp), volume24h: n(m.volume_24h_fp), openInterest: n(m.open_interest_fp),
      lastPrice: n(m.last_price_dollars), closeTime: m.close_time, expectedExpiration: m.expected_expiration_time,
      rulesPrimary: m.rules_primary, rulesSecondary: m.rules_secondary,
      observedAt: new Date().toISOString(),
      sourceUrl: `${DEMO_REST}/markets/${encodeURIComponent(m.ticker)}`,
    };
    state.source = 'live';
    if (b) {
      state.book = {
        yes: (b.yes_dollars ?? []).map(([p, q]) => [Number(p), Number(q)]),
        no: (b.no_dollars ?? []).map(([p, q]) => [Number(p), Number(q)]),
        sourceUrl: `${DEMO_REST}/markets/${encodeURIComponent(ticker)}/orderbook`,
      };
    }
    return true;
  } catch { return false; }
}

async function loadHistory() {
  // Chart points: the collector's own observations, which carry the time the
  // response was received - not the time the page loaded.
  try {
    const live = await loadLocal('data/live/state.json');
    const tracked = live.tracked?.[ticker];
    if (tracked?.history?.length) {
      state.history = tracked.history;
      return;
    }
  } catch { /* fall through */ }
  // Snapshot capture has exactly one point per market; say so rather than
  // drawing a line through a single observation.
  const m = state.market;
  if (m?.yesBid != null || m?.yesAsk != null) {
    const mid = m.yesBid != null && m.yesAsk != null ? (m.yesBid + m.yesAsk) / 2 : null;
    state.history = mid == null ? [] : [{ t: m.observedAt, mid, bid: m.yesBid, ask: m.yesAsk }];
  }
}

async function loadAlertsAndResolution() {
  try {
    const feed = await loadLocal('data/live/feed.json');
    state.alerts = (feed.alerts ?? []).filter((a) => a.marketTicker === ticker);
  } catch { state.alerts = []; }
  try {
    const live = await loadLocal('data/live/state.json');
    state.resolution = live.resolutions?.[ticker] ?? null;
  } catch { state.resolution = null; }
}

function deriveLevels(book) {
  const yes = (book?.yes ?? []).slice().sort((a, b) => b[0] - a[0]);
  const no = (book?.no ?? []).slice().sort((a, b) => b[0] - a[0]);
  // A NO bid at q is a YES ask at 1-q.
  const asks = no.map(([q, size]) => [Math.round((1 - q) * 10000) / 10000, size]).sort((a, b) => a[0] - b[0]);
  return { yes, asks };
}

function renderHeader() {
  const m = state.market;
  if (!m) {
    setText(el['m-title'], ticker ? `Market ${ticker} not found on this board` : 'No market selected');
    el['m-rules'].textContent = ticker
      ? 'This ticker is not in the committed capture. Open the market on Kalshi to see it live.'
      : 'Pick a market from the board or the markets list.';
    return;
  }
  document.title = `${m.title ?? ticker} · Tradebot1`;
  setText(el['m-title'], m.title ?? ticker);
  setText(el['crumb'], m.title ?? ticker);
  setText(el['m-ticker'], m.ticker);
  setText(el['m-topic'], TOPIC_LABELS[m.topic] ?? m.topic ?? 'unclassified');
  setText(el['m-status'], `status: ${m.status ?? dash}`);
  const resolved = m.result === 'yes' || m.result === 'no';
  setText(el['m-result'], resolved ? `result: ${m.result.toUpperCase()}` : 'result: not published');
  el['m-result'].className = `badge ${resolved ? m.result : ''}`;
  setText(el['m-rules'], m.rulesPrimary ?? 'The exchange did not return settlement rules for this market in this capture.');

  const { yes, asks } = deriveLevels(state.book);
  const bestBid = yes.length ? yes[0][0] : null;
  const bestAsk = asks.length ? asks[0][0] : null;
  setText(el['m-bid'], cents(bestBid ?? m.yesBid));
  setText(el['m-ask'], cents(bestAsk));
  setText(el['m-spread'], bestBid != null && bestAsk != null ? `${Math.round((bestAsk - bestBid) * 100)}¢` : dash);
  setText(el['m-volume'], int(m.volume24h));
  setText(el['m-oi'], int(m.openInterest));
}

function renderLadders() {
  const { yes, asks } = deriveLevels(state.book);
  const maxYes = Math.max(0, ...yes.map(([, s]) => s));
  const maxAsk = Math.max(0, ...asks.map(([, s]) => s));

  const bookUrl = state.book?.sourceUrl ?? state.market?.sourceUrl;
  el['ladder-yes'].innerHTML = yes.length
    ? yes.slice(0, 12).map(([p, s]) => `<tr>
        <td class="mono">${esc(cents(p))}</td>
        <td class="num">${esc(num(s, 2))}</td>
        <td class="num">${esc(money(p * s, 2))}</td>
        <td style="min-width:80px"><div class="depthbar"><span style="width:${maxYes ? (s / maxYes) * 100 : 0}%"></span></div></td>
        <td class="src">${sourceLink(bookUrl, 'book')}</td>
      </tr>`).join('')
    : '<tr><td colspan="5" class="empty">The exchange returned no YES bids for this market.</td></tr>';

  el['ladder-ask'].innerHTML = asks.length
    ? asks.slice(0, 12).map(([p, s]) => `<tr>
        <td class="mono">${esc(cents(p))}</td>
        <td class="num">${esc(num(s, 2))}</td>
        <td class="num">${esc(money(p * s, 2))}</td>
        <td style="min-width:80px"><div class="depthbar"><span style="width:${maxAsk ? (s / maxAsk) * 100 : 0}%"></span></div></td>
        <td class="src">${sourceLink(bookUrl, 'book')}</td>
      </tr>`).join('')
    : '<tr class="placeholder" data-nosource="true"><td colspan="5" class="empty">No NO bids, so no YES asks can be derived.</td></tr>';

  setText(el['depth-bid'], yes.length ? num(yes.reduce((s, [, q]) => s + q, 0), 2) : dash);
  setText(el['depth-ask'], asks.length ? num(asks.reduce((s, [, q]) => s + q, 0), 2) : dash);
}

function renderChart() {
  const win = WINDOWS.find((w) => w.id === state.window) ?? WINDOWS[3];
  const now = Date.now();
  const points = bucketSeries(state.history, win.ms, win.bucket, now);
  const marks = document.getElementById('show-alerts')?.checked
    ? state.alerts.map((a) => ({ observedAt: a.observedAt, delta: a.delta }))
    : [];
  const out = drawChart(el.chart, {
    points,
    windowMs: win.ms,
    now,
    alerts: marks,
    emptyMessage: state.history.length
      ? `No observation in the last ${win.label}. Widen the window.`
      : 'No price observations stored for this market yet.',
  });
  el['chart-note'].textContent = state.history.length
    ? `${state.history.length} stored observations for this market, ${out.drawn} inside this ${win.label} window after bucketing every ${Math.round(win.bucket / 1000)}s. Observation times come from the collector's own clock.`
    : 'A line needs at least two observations; this market has none stored yet. The collector adds them on each cycle.';
}

function renderResolution() {
  const r = state.resolution;
  if (!r) {
    el['res-table'].querySelector('tbody').innerHTML = `<tr><td colspan="5" class="empty">
      No resolution record yet. The collector checks every tracked market each cycle and records the
      exchange's status and result when it changes.</td></tr>`;
    return;
  }
  const resolved = r.result === 'yes' || r.result === 'no';
  el['res-table'].querySelector('tbody').innerHTML = `<tr>
    <td>${esc(r.status ?? dash)}${r.resolution?.final ? ' <span class="badge ok">final</span>' : ''}</td>
    <td>${resolved ? `<span class="badge ${r.result === 'yes' ? 'yes' : 'no'}">${esc(r.result.toUpperCase())}</span>` : esc(r.resolution?.label ?? 'not published')}</td>
    <td class="mono">${esc(stamp(r.checkedAt))}</td>
    <td class="mono">${esc(r.settlementTs ? stamp(new Date(r.settlementTs * 1000).toISOString()) : dash)}</td>
    <td class="src">${sourceLink(r.sourceUrl, 'exchange')}</td>
  </tr>`;
}

function renderDetails() {
  const m = state.market ?? {};
  const rows = [
    ['Ticker', m.ticker, m.sourceUrl],
    ['Event ticker', m.eventTicker, m.sourceUrl],
    ['Status', m.status, m.sourceUrl],
    ['Result', m.result === '' || m.result == null ? 'not published' : m.result, m.sourceUrl],
    ['Last traded price', m.lastPrice != null ? cents(m.lastPrice) : dash, m.sourceUrl],
    ['24h volume', m.volume24h != null ? int(m.volume24h) : dash, m.sourceUrl],
    ['Total volume', m.volume != null ? int(m.volume) : dash, m.sourceUrl],
    ['Open interest', m.openInterest != null ? int(m.openInterest) : dash, m.sourceUrl],
    ['Close time (UTC)', m.closeTime ?? dash, m.sourceUrl],
    ['Expected expiration (UTC)', m.expectedExpiration ?? dash, m.sourceUrl],
    ['Observed at', state.market?.observedAt ? stamp(state.market.observedAt) : dash, m.sourceUrl],
    ['YES bid / ask (exchange fields)', `${cents(m.yesBid)} / ${cents(m.yesAsk)}`, m.sourceUrl],
    ['Order book (bids only, raw)', state.book ? 'loaded' : 'not loaded', state.book?.sourceUrl ?? m.sourceUrl],
    ['Settlement rules', m.rulesPrimary || dash, m.sourceUrl],
  ];
  el['m-details'].querySelector('tbody').innerHTML = rows.map(([k, v, u]) => `<tr>
    <th scope="row" style="text-transform:none;letter-spacing:0;font-size:.82rem;background:transparent;position:static">${esc(k)}</th>
    <td class="mono">${esc(v ?? dash)}</td>
    <td class="src">${sourceLink(u, 'field')}</td>
  </tr>`).join('');
}

async function runPaperTrade() {
  const side = el['pt-side'].value;
  const count = Number(el['pt-count'].value);
  const price = Number(el['pt-price'].value);
  const out = el['pt-out'];
  if (!(count > 0)) { out.innerHTML = '<div class="notice danger">Enter a positive whole number of contracts.</div>'; return; }
  if (!(price > 0 && price < 1)) { out.innerHTML = '<div class="notice danger">Enter a price between $0.01 and $0.99.</div>'; return; }
  // Fee is the published taker fee, rounded up to the whole cent, which is the
  // rule that reproduces Kalshi's own fee table (see flagged.html#F-02).
  const modelFee = Math.ceil(0.07 * count * price * (1 - price) * 100 - 1e-9) / 100;
  const cost = count * price;
  const maxProfit = count - cost;
  out.innerHTML = `<div class="grid cols-4">
      <div class="stat"><span class="k">Contracts</span><span class="v">${esc(int(count))}</span></div>
      <div class="stat"><span class="k">Cost at limit</span><span class="v">${esc(money(cost, 2))}</span></div>
      <div class="stat"><span class="k">Taker fee (published formula)</span><span class="v">${esc(money(modelFee, 2))}</span></div>
      <div class="stat"><span class="k">Payout if ${side === 'yes' ? 'YES' : 'NO'} wins</span><span class="v">${esc(money(count, 2))}</span></div>
    </div>
    <p class="small dim" style="margin-top:10px">
      Net if it wins: ${esc(money(maxProfit - modelFee, 2))} · net if it loses: ${esc(money(-cost - modelFee, 2))}.
      This is arithmetic, not an execution: no order is sent and the fill is not assumed.
      <a href="https://kalshi.com/docs/kalshi-fee-schedule.pdf" target="_blank" rel="noopener noreferrer nofollow">Fee schedule ↗</a>
    </p>`;
}

async function init() {
  setText(el['m-ticker'], ticker || dash);
  await loadSnapshotMarket();
  await loadHistory();
  await loadAlertsAndResolution();
  if (!state.market) {
    await loadLiveMarket();
    await loadHistory();
  }
  renderHeader();
  renderLadders();
  renderChart();
  renderResolution();
  renderDetails();

  renderBanner(el['data-banner'], {
    state: state.source === 'live' ? 'live' : 'snapshot',
    headline: state.source === 'live' ? 'Read from the official demo API just now' : 'Committed capture',
    detail: state.source === 'live'
      ? 'This market, its order book and its status were fetched by this browser.'
      : 'Fetched from data/snapshot.json because this browser could not read the demo API directly.',
    at: state.market?.observedAt,
  });

  // Prefill the paper-trade price with the executable side for the chosen side.
  const { yes, asks } = deriveLevels(state.book);
  el['pt-price'].value = (asks.length ? asks[0][0] : (yes.length ? yes[0][0] : 0.5)).toFixed(2);
  el['pt-side'].addEventListener('change', () => {
    const d = deriveLevels(state.book);
    el['pt-price'].value = (el['pt-side'].value === 'yes'
      ? (d.asks.length ? d.asks[0][0] : 0.5)
      : (d.yes.length ? Math.round((1 - d.yes[0][0]) * 100) / 100 : 0.5)).toFixed(2);
  });
  el['pt-run'].addEventListener('click', runPaperTrade);

  document.getElementById('window-toggle').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-win]');
    if (!btn) return;
    state.window = btn.dataset.win;
    for (const b of document.querySelectorAll('#window-toggle button')) b.setAttribute('aria-pressed', String(b === btn));
    renderChart();
  });
  document.getElementById('show-alerts').addEventListener('change', renderChart);

  // Keep the chart honest: re-render on resize, and refresh if the market is live.
  window.addEventListener('resize', () => renderChart());
  if (state.source === 'live') setInterval(() => { loadLiveMarket().then(() => { renderHeader(); renderLadders(); renderChart(); }); }, 30000);
}

init().catch((err) => {
  renderBanner(el['data-banner'], { state: 'error', headline: 'Could not load this market', detail: err.message });
});
