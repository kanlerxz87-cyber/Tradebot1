// The landing board: ranks live markets by resting dollars, summarises the five
// topics, and fills the headline figures.
//
// Data flow: try the official demo API from this browser; if that is blocked or
// empty, fall back to the committed capture in data/snapshot.json. The banner
// says which one is on screen, with the observation time.

import {
  loadLocal, probeApi, renderBanner, money, cents, num, int, esc, dash, timeAgo, stamp, sourceLink,
  DEMO_REST, TOPIC_LABELS,
} from './common.js';

const TOPIC_ORDER = ['gas', 'elections', 'culture', 'crypto', 'golf'];

const state = {
  source: 'snapshot',
  observedAt: null,
  markets: [],
  orderbooks: new Map(),
  series: [],
  alerts: [],
  resolutions: {},
};

function marketFromApi(m, topic) {
  return {
    ticker: m.ticker,
    eventTicker: m.event_ticker,
    topic,
    title: m.title,
    yesBid: n(m.yes_bid_dollars),
    yesAsk: n(m.yes_ask_dollars),
    volume24h: n(m.volume_24h_fp),
    volume: n(m.volume_fp),
    openInterest: n(m.open_interest_fp),
    status: m.status,
    result: m.result,
    closeTime: m.close_time,
    observedAt: new Date().toISOString(),
    sourceUrl: `${DEMO_REST}/markets/${encodeURIComponent(m.ticker)}`,
  };
}

const n = (v) => (v === null || v === undefined || v === '' ? null : (Number.isFinite(Number(v)) ? Number(v) : null));

async function loadSnapshot() {
  const snap = await loadLocal('data/snapshot.json');
  state.source = 'snapshot';
  state.observedAt = snap?.meta?.capturedAt ?? null;
  state.markets = (snap?.markets ?? []).filter((m) => m.topic);
  state.series = snap?.series ?? [];
  // Resting dollars from the captured ladders where they exist.
  for (const m of snap?.markets ?? []) {
    if (!m.orderbook) continue;
    try {
      const ob = JSON.parse(m.orderbook.raw).orderbook_fp;
      const levels = (ob.yes_dollars ?? []).map(([p, q]) => [Number(p), Number(q)]);
      state.orderbooks.set(m.ticker, {
        restingDollars: levels.reduce((s, [p, q]) => s + p * q, 0),
        restingContracts: levels.reduce((s, [, q]) => s + q, 0),
        bestBid: levels.length ? Math.max(...levels.map(([p]) => p)) : null,
        sourceUrl: m.orderbook.sourceUrl,
      });
    } catch { /* a malformed fragment is skipped, not guessed */ }
  }
  return snap;
}

async function loadLive() {
  const probe = await probeApi();
  if (!probe.ok) return false;
  // Sample a bounded number of series per topic; the same discovery rule the
  // collector uses (category for three topics, Golf tag for golf).
  const found = [];
  const probes = [
    { topic: 'gas', url: `${DEMO_REST}/series?tags=Gas` },
    { topic: 'elections', url: `${DEMO_REST}/series?category=Elections` },
    { topic: 'culture', url: `${DEMO_REST}/series?category=Culture` },
    { topic: 'crypto', url: `${DEMO_REST}/series?category=Crypto` },
    { topic: 'golf', url: `${DEMO_REST}/series?tags=Golf` },
  ];
  const results = await Promise.allSettled(probes.map((p) => fetch(p.url).then((r) => (r.ok ? r.json() : { series: [] }))));
  results.forEach((res, i) => {
    if (res.status !== 'fulfilled') return;
    for (const s of res.value?.series ?? []) found.push({ ...s, topic: probes[i].topic });
  });
  if (!found.length) return false;

  const perTopic = new Map();
  for (const s of found) {
    const list = perTopic.get(s.topic) ?? [];
    if (list.length < 6) list.push(s);
    perTopic.set(s.topic, list);
  }
  const marketFetches = [];
  for (const [topic, list] of perTopic) {
    for (const s of list) {
      marketFetches.push(
        fetch(`${DEMO_REST}/markets?series_ticker=${encodeURIComponent(s.ticker)}&status=open&limit=40`)
          .then((r) => (r.ok ? r.json() : { markets: [] }))
          .then((j) => ({ topic, series: s, markets: j.markets ?? [] }))
          .catch(() => ({ topic, series: s, markets: [] })),
      );
    }
  }
  const pages = await Promise.all(marketFetches);
  const markets = [];
  const series = [];
  const nowIso = new Date().toISOString();
  for (const page of pages) {
    series.push({
      ticker: page.series.ticker, title: page.series.title, category: page.series.category,
      tags: page.series.tags, topic: page.topic, openMarkets: page.markets.length,
      sourceUrl: `${DEMO_REST}/series/${encodeURIComponent(page.series.ticker)}`,
    });
    for (const m of page.markets) {
      markets.push({ ...marketFromApi(m, page.topic), observedAt: nowIso });
    }
  }
  if (!markets.length) return false;

  state.source = 'live';
  state.observedAt = nowIso;
  state.markets = markets;
  state.series = series;
  // Live order books for the markets shown, in one batch of reads.
  const top = markets.slice(0, 24);
  const books = await Promise.allSettled(top.map((m) => fetch(`${DEMO_REST}/markets/${encodeURIComponent(m.ticker)}/orderbook`).then((r) => (r.ok ? r.json() : null))));
  books.forEach((res, i) => {
    if (res.status !== 'fulfilled' || !res.value) return;
    const ob = res.value.orderbook_fp ?? {};
    const levels = (ob.yes_dollars ?? []).map(([p, q]) => [Number(p), Number(q)]);
    state.orderbooks.set(top[i].ticker, {
      restingDollars: levels.reduce((s, [p, q]) => s + p * q, 0),
      restingContracts: levels.reduce((s, [, q]) => s + q, 0),
      bestBid: levels.length ? Math.max(...levels.map(([p]) => p)) : null,
      sourceUrl: `${DEMO_REST}/markets/${encodeURIComponent(top[i].ticker)}/orderbook`,
      observedAt: nowIso,
    });
  });
  return true;
}

async function loadCommittedFeeds() {
  try {
    const feed = await loadLocal('data/live/feed.json');
    state.alerts = feed.alerts ?? [];
  } catch { state.alerts = []; }
  try {
    const live = await loadLocal('data/live/state.json');
    state.resolutions = live.resolutions ?? {};
    state.coverage = live.coverage ?? {};
    state.discovery = live.discovery ?? {};
    state.exchange = live.exchange ?? null;
  } catch { /* the board still works from the snapshot */ }
  try {
    const snap = await loadLocal('data/snapshot.json');
    state.series = state.series.length ? state.series : (snap.series ?? []);
  } catch { /* ignore */ }
}

function restingFor(m) {
  const book = state.orderbooks.get(m.ticker);
  return book?.restingDollars ?? null;
}

function renderRank(mode) {
  const rows = state.markets
    .map((m) => {
      const book = state.orderbooks.get(m.ticker);
      const move = Math.abs(largestAlertFor(m.ticker)?.delta ?? 0);
      return { ...m, resting: book?.restingDollars ?? null, move };
    })
    .sort((a, b) => {
      if (mode === 'volume') return (b.volume24h ?? -1) - (a.volume24h ?? -1);
      if (mode === 'move') return (b.move ?? 0) - (a.move ?? 0) || (b.resting ?? -1) - (a.resting ?? -1);
      return (b.resting ?? -1) - (a.resting ?? -1) || (b.volume24h ?? -1) - (a.volume24h ?? -1);
    })
    .slice(0, 15);

  const tbody = document.querySelector('#rank-table tbody');
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">No markets in the five topics were on the board when this page was built.<br>
      Gas and golf have no open markets in parts of the demo catalogue; see <a href="flagged.html#F-03">F-03</a>.</td></tr>`;
    return;
  }
  // Some demo markets quote a one-sided book, so "resting dollars" is genuinely
  // zero. Say that in one line above the table instead of leaving the ranking
  // reader to guess why every figure is a dash.
  const ranked = rows.filter((r) => r.resting != null && r.resting > 0).length;
  const rankNote = document.getElementById('rank-note');
  if (rankNote) {
    rankNote.innerHTML = ranked
      ? `Ranked by resting bid dollars. ${rows.length - ranked} of the ${rows.length} rows below have an empty book and are shown with a dash rather than a zero.`
      : `None of the ${rows.length} markets below has a bid resting on its book in this capture, so the ranking falls back to 24-hour volume and every dollar figure reads as a dash. That is the exchange's data, not a missing value.`;
  }

  tbody.innerHTML = rows.map((m, i) => {
    const book = state.orderbooks.get(m.ticker);
    const alert = largestAlertFor(m.ticker);
    return `<tr>
      <td class="num dim">${i + 1}</td>
      <td><a href="market.html?t=${encodeURIComponent(m.ticker)}">${esc(m.title ?? m.ticker)}</a>
        <span class="sub mono">${esc(m.ticker)}${alert ? ` · largest logged swing ${alert.delta > 0 ? '+' : '−'}$${Math.abs(alert.delta).toFixed(2)}` : ''}</span></td>
      <td><span class="badge">${esc(TOPIC_LABELS[m.topic] ?? m.topic)}</span></td>
      <td class="num">${esc(cents(m.yesBid))}</td>
      <td class="num">${esc(cents(m.yesAsk))}</td>
      <td class="num">${m.resting != null ? esc(money(m.resting, 2)) : esc(dash)}</td>
      <td class="num">${esc(int(m.volume24h))}</td>
      <td class="num"><span class="dim">${esc(timeAgo(m.observedAt))}</span></td>
      <td class="src">${sourceLink(book?.sourceUrl ?? m.sourceUrl, book ? 'book' : 'market')}</td>
    </tr>`;
  }).join('');
}

function largestAlertFor(ticker) {
  const list = state.alerts.filter((a) => a.marketTicker === ticker);
  if (!list.length) return null;
  return list.reduce((best, a) => (Math.abs(a.delta) > Math.abs(best.delta) ? a : best));
}

function renderTopics() {
  const byTopicSeries = new Map(TOPIC_ORDER.map((t) => [t, new Set()]));
  for (const s of state.series) {
    if (!byTopicSeries.has(s.topic)) continue;
    byTopicSeries.get(s.topic).add(s.ticker);
  }
  const marketsByTopic = new Map(TOPIC_ORDER.map((t) => [t, 0]));
  for (const m of state.markets) marketsByTopic.set(m.topic, (marketsByTopic.get(m.topic) ?? 0) + 1);
  const alertsByTopic = new Map(TOPIC_ORDER.map((t) => [t, 0]));
  for (const a of state.alerts) alertsByTopic.set(a.topic, (alertsByTopic.get(a.topic) ?? 0) + 1);
  const resolvedByTopic = new Map(TOPIC_ORDER.map((t) => [t, 0]));
  for (const r of Object.values(state.resolutions)) {
    if (r.result !== 'yes' && r.result !== 'no') continue;
  }

  const discoveryNote = {
    gas: 'Series tag <code>Gas</code>',
    elections: 'Series category <code>Elections</code>',
    culture: 'Series category <code>Culture</code>',
    crypto: 'Series category <code>Crypto</code>',
    golf: 'Series tag <code>Golf</code>',
  };
  const discoverySource = {
    gas: `${DEMO_REST}/series?tags=Gas`,
    elections: `${DEMO_REST}/series?category=Elections`,
    culture: `${DEMO_REST}/series?category=Culture`,
    crypto: `${DEMO_REST}/series?category=Crypto`,
    golf: `${DEMO_REST}/series?tags=Golf`,
  };

  document.querySelector('#topic-table tbody').innerHTML = TOPIC_ORDER.map((t) => `<tr>
    <td><a href="categories/${t}.html"><strong>${esc(TOPIC_LABELS[t])}</strong></a></td>
    <td class="small">${discoveryNote[t]}</td>
    <td class="num">${esc(num(byTopicSeries.get(t)?.size ?? null, 0))}</td>
    <td class="num">${esc(int(marketsByTopic.get(t) ?? null))}</td>
    <td class="num">${esc(int(alertsByTopic.get(t) ?? 0))}</td>
    <td class="num">${esc(dash)}<span class="sub">awaiting finalized</span></td>
    <td class="src">${sourceLink(discoverySource[t], 'series')}</td>
  </tr>`).join('');

  const cards = document.querySelector('#topic-cards');
  const blurb = {
    gas: 'Fuel prices. In the demo catalogue this currently means the diesel series.',
    elections: 'Contests and candidates, worldwide.',
    culture: 'Bans, awards and entertainment.',
    crypto: 'Bitcoin, Ethereum and other assets.',
    golf: 'PGA, LIV and major outcomes.',
  };
  cards.innerHTML = TOPIC_ORDER.map((t) => `<a class="card card-link tight" href="categories/${t}.html">
      <div class="stat"><span class="k">${esc(TOPIC_LABELS[t])}</span>
      <span class="v">${esc(int(marketsByTopic.get(t) ?? 0))}</span>
      <span class="s">${esc(blurb[t])}</span></div>
    </a>`).join('');
}

function renderStats() {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('stat-markets', int(state.markets.length));
  set('stat-alerts', int(state.alerts.length));
  const resolved = Object.values(state.resolutions ?? {}).filter((r) => r.result === 'yes' || r.result === 'no');
  const yes = resolved.filter((r) => r.result === 'yes').length;
  set('stat-resolved', resolved.length ? `${yes} yes / ${resolved.length - yes} no` : dash);
  loadLocal('data/live/portfolio.json').then((p) => {
    const eq = p?.summary?.equity;
    set('stat-equity', eq == null ? dash : money(eq, 2));
    const sub = document.getElementById('stat-equity-sub');
    if (sub) sub.textContent = eq == null ? 'no simulated trades yet' : `${signed(eq - (p.startingCash ?? 0))} vs ${money(p.startingCash ?? 0, 0)} start`;
  }).catch(() => set('stat-equity', dash));
}

const signed = (v) => (v == null ? dash : `${v > 0 ? '+' : v < 0 ? '−' : ''}$${Math.abs(v).toFixed(2)}`);

function renderBanners() {
  const banner = document.getElementById('data-banner');
  if (state.source === 'live') {
    renderBanner(banner, {
      state: 'live',
      headline: 'Reading the official demo API from this browser',
      detail: `${state.markets.length} open markets across the five topics, fetched just now.`,
      at: state.observedAt,
    });
  } else {
    renderBanner(banner, {
      state: 'snapshot',
      headline: 'Showing the committed capture',
      detail: 'This browser could not read the demo API directly, so the rows come from data/snapshot.json, captured once and stored in the repository.',
      at: state.observedAt,
    });
  }
}

async function init() {
  await loadCommittedFeeds();
  await loadSnapshot();
  renderStats();
  renderTopics();
  renderRank('notional');
  renderBanners();

  document.getElementById('rank-toggle')?.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-mode]');
    if (!btn) return;
    for (const b of document.querySelectorAll('#rank-toggle button')) b.setAttribute('aria-pressed', String(b === btn));
    renderRank(btn.dataset.mode);
  });

  const live = await loadLive().catch(() => false);
  if (live) {
    renderStats();
    renderTopics();
    renderRank(document.querySelector('#rank-toggle button[aria-pressed="true"]')?.dataset.mode ?? 'notional');
    renderBanners();
  }
}

init().catch((err) => {
  const banner = document.getElementById('data-banner');
  renderBanner(banner, { state: 'error', headline: 'Could not load data', detail: err.message });
});
