// A topic page. The topic is read from the page's own file name, so the same
// code serves all five pages and there is no second copy of the rules.

import { loadLocal, renderBanner, cents, int, num, esc, dash, stamp, timeAgo, sourceLink, signedMoney, sitePath } from './common.js';

const TOPIC = (location.pathname.split('/').pop() ?? '').replace('.html', '');
const TOPIC_LABEL = { gas: 'Gas prices', elections: 'Elections', culture: 'Culture', crypto: 'Crypto', golf: 'Golf' }[TOPIC] ?? TOPIC;

const BLURB = {
  gas: 'US fuel prices — retail gasoline (KXAAAGASM / KXAAAGASW under Oil and energy) and weekly diesel (flag F-03).',
  elections: 'Candidate, party and ballot contests, found through the official series category Elections.',
  culture: 'Bans, awards, entertainment and social events across Culture, Entertainment and Social categories.',
  crypto: 'Bitcoin, Ethereum and other digital-asset contracts, found through the official series category Crypto, settling on CF Benchmarks indices.',
  golf: 'PGA, LIV and major outcomes. Golf is not a Kalshi category, so this topic uses the official Golf tag on series whose category is Sports (flag F-04).',
};

const DISCOVERY = {
  gas: { label: 'series tag Oil and energy', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Oil%20and%20energy' },
  elections: { label: 'series category Elections', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Elections' },
  culture: { label: 'series category Entertainment', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Entertainment' },
  crypto: { label: 'series category Crypto', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?category=Crypto' },
  golf: { label: 'series tag Golf', url: 'https://external-api.demo.kalshi.co/trade-api/v2/series?tags=Golf' },
};

function setText(id, v) { const n = document.getElementById(id); if (n) n.textContent = v; }

async function init() {
  document.getElementById('cat-blurb').textContent = BLURB[TOPIC] ?? '';

  let snap = { series: [], markets: [], meta: {} };
  let live = { resolutions: {}, coverage: {}, discovery: {} };
  let feed = { alerts: [] };

  try { snap = await loadLocal('data/snapshot.json'); } catch { /* keep defaults */ }
  try { live = await loadLocal('data/live/state.json'); } catch { /* keep defaults */ }
  try { feed = await loadLocal('data/live/feed.json'); } catch { /* keep defaults */ }

  const series = (snap.series ?? []).filter((s) => s.topic === TOPIC);
  const markets = (snap.markets ?? []).filter((m) => m.topic === TOPIC)
    .map((m) => ({ ...m, observedAt: m.observedAt ?? snap.meta?.capturedAt }));
  // Live-collected markets for this topic, if the collector has run.
  const trackedLive = Object.values(live.tracked ?? {}).filter((t) => t.topic === TOPIC);
  const liveTickers = new Set(trackedLive.map((t) => t.marketTicker));
  const knownTickers = new Set(markets.map((m) => m.ticker));

  setText('cat-series', series.length ? int(series.length) : (live.discovery?.[TOPIC]?.seriesFound != null ? int(live.discovery[TOPIC].seriesFound) : dash));
  setText('cat-markets', markets.length || trackedLive.length ? int(markets.length + [...liveTickers].filter((t) => !knownTickers.has(t)).length) : dash);

  const alerts = (feed.alerts ?? []).filter((a) => a.topic === TOPIC);
  setText('cat-alerts', int(alerts.length));

  const resolutions = Object.entries(live.resolutions ?? {}).filter(([, r]) => {
    const topicMarkets = new Set([...knownTickers, ...liveTickers]);
    return topicMarkets.has(r.ticker);
  }).map(([, r]) => r);
  const resolved = resolutions.filter((r) => r.result === 'yes' || r.result === 'no');
  setText('cat-resolved', resolved.length
    ? `${resolved.filter((r) => r.result === 'yes').length} yes / ${resolved.filter((r) => r.result === 'no').length} no`
    : dash);

  renderBanner(document.getElementById('data-banner'), {
    state: 'snapshot',
    headline: `${TOPIC_LABEL} — committed capture`,
    detail: markets.length
      ? `${markets.length} markets from ${series.length ? `${series.length} series` : 'the capture'} in this topic.`
      : 'No market in this topic is in the committed capture. The scheduled collector will add any it finds.',
    at: snap.meta?.capturedAt,
  });

  // discovery table
  const d = DISCOVERY[TOPIC];
  const coverage = live.coverage?.[TOPIC];
  document.querySelector('#discovery-table tbody').innerHTML = `<tr>
    <td>${esc(d.label)}</td>
    <td class="mono small">GET /series${esc(new URL(d.url).search)}</td>
    <td>${esc(series.length ? `${series.length} series in the capture` : 'see the source response')}
      ${coverage ? `<span class="sub">collector read ${esc(int(coverage.marketsObserved))} markets this run</span>` : ''}</td>
    <td class="src">${sourceLink(d.url, 'series')}</td>
  </tr>`;

  // groups
  const groups = document.getElementById('cat-groups');
  if (!markets.length) {
    groups.innerHTML = `<div class="card empty">No open market in this topic is in the committed capture.<br>
      <span class="small">This is a real state of the demo exchange, not a missing row: for gas, the series exist but their markets query returns nothing (see <a href="${sitePath('flagged.html')}#F-03">F-03</a>).</span></div>`;
  } else {
    const byEvent = new Map();
    for (const m of markets) {
      const key = m.eventTicker || m.ticker;
      if (!byEvent.has(key)) byEvent.set(key, []);
      byEvent.get(key).push(m);
    }
    groups.innerHTML = [...byEvent.entries()].map(([event, list]) => `<div class="card">
      <div class="toolbar" style="margin-bottom:8px">
        <h3 style="margin:0">${esc(list[0].title?.split('?')[0] ?? event)}</h3>
        <span class="badge mono">${esc(event)}</span>
        <span class="badge">${esc(int(list.length))} markets</span>
      </div>
      <div class="table-wrap"><table class="compact">
        <thead><tr><th>Market</th><th class="num">YES bid</th><th class="num">YES ask</th><th class="num">24h vol</th><th class="num">Open interest</th><th>Status</th><th>Source</th></tr></thead>
        <tbody>${list.map((m) => `<tr>
          <td><a href="${sitePath('market.html')}?t=${encodeURIComponent(m.ticker)}">${esc(m.title ?? m.ticker)}</a><span class="sub mono">${esc(m.ticker)}</span></td>
          <td class="num">${esc(cents(m.yesBid))}</td>
          <td class="num">${esc(cents(m.yesAsk))}</td>
          <td class="num">${esc(int(m.volume24h))}</td>
          <td class="num">${esc(int(m.openInterest))}</td>
          <td><span class="badge">${esc(m.status ?? dash)}</span></td>
          <td class="src">${sourceLink(m.sourceUrl, 'market')}</td>
        </tr>`).join('')}</tbody>
      </table></div>
    </div>`).join('');
  }

  // resolutions
  const resBody = document.querySelector('#cat-resolutions tbody');
  if (resolutions.length) {
    resBody.innerHTML = resolutions.map((r) => {
      const ok = r.result === 'yes' || r.result === 'no';
      return `<tr>
        <td class="mono small">${esc(r.ticker)}</td>
        <td>${esc(r.status ?? dash)}</td>
        <td>${ok ? `<span class="badge ${r.result === 'yes' ? 'yes' : 'no'}">${esc(r.result.toUpperCase())}</span>` : esc(r.resolution?.label ?? 'not published')}</td>
        <td class="mono">${esc(stamp(r.checkedAt))}</td>
        <td class="mono">${esc(r.settlementTs ? stamp(new Date(r.settlementTs * 1000).toISOString()) : dash)}</td>
        <td class="src">${sourceLink(r.sourceUrl, 'exchange')}</td>
      </tr>`;
    }).join('');
  }

  // settlement sources
  const sourceRows = new Map();
  for (const s of series) {
    for (const ss of s.settlementSources ?? []) {
      if (!ss?.url) continue;
      if (!sourceRows.has(ss.url)) sourceRows.set(ss.url, { name: ss.name, url: ss.url, series: new Set() });
      sourceRows.get(ss.url).series.add(s.ticker);
    }
  }
  if (sourceRows.size) {
    document.querySelector('#sources-table tbody').innerHTML = [...sourceRows.values()].slice(0, 20).map((r) => `<tr>
      <td>${esc(r.name || r.url)}</td>
      <td class="mono small">${esc([...r.series].join(', '))}</td>
      <td class="src">${sourceLink(r.url, 'open')}</td>
    </tr>`).join('');
  }

  // alerts
  if (alerts.length) {
    document.querySelector('#cat-alert-table tbody').innerHTML = alerts.slice(0, 200).map((a) => `<tr>
      <td class="mono nowrap">${esc(stamp(a.observedAt))}</td>
      <td>${esc(a.title ?? a.marketTicker)}<span class="sub mono">${esc(a.marketTicker)}</span></td>
      <td class="num">${esc(cents(a.from))}</td>
      <td class="num">${esc(cents(a.to))}</td>
      <td class="num ${a.delta >= 0 ? 'up' : 'down'}">${esc(signedMoney(a.delta))}</td>
      <td class="num">${esc(a.score ?? dash)}</td>
      <td class="src">${sourceLink(a.marketUrl, 'market')}</td>
    </tr>`).join('');
  }
}

init().catch((err) => {
  renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Could not load this topic', detail: err.message });
});
