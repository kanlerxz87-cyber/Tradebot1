// markets.html — all tracked markets, grouped by topic then event.

import { loadLocal, renderBanner, cents, int, esc, dash, stamp, timeAgo, sourceLink, TOPIC_LABELS } from './common.js';

const TOPIC_ORDER = ['gas', 'elections', 'culture', 'crypto', 'golf'];
let rows = [];
let resolutions = {};
let filterState = 'all';
let query = '';

function stateOf(m) {
  const r = resolutions[m.ticker];
  const result = r?.result ?? m.result ?? '';
  const status = r?.status ?? m.status ?? '';
  const resolved = (result === 'yes' || result === 'no') && status === 'finalized';
  if (resolved) return { key: 'resolved', label: `${result.toUpperCase()}`, cls: result === 'yes' ? 'yes' : 'no', result, status };
  if (['closed', 'determined', 'disputed', 'amended'].includes(status)) return { key: 'awaiting', label: 'awaiting result', cls: 'warn', result, status };
  return { key: 'open', label: status || 'open', cls: '', result, status };
}

function matches(m) {
  const s = stateOf(m);
  if (filterState !== 'all' && s.key !== filterState) return false;
  if (!query) return true;
  const q = query.toLowerCase();
  return (m.title ?? '').toLowerCase().includes(q) || (m.ticker ?? '').toLowerCase().includes(q) || (m.eventTicker ?? '').toLowerCase().includes(q);
}

function render() {
  const groups = document.getElementById('groups');
  const visible = rows.filter(matches);
  if (!visible.length) {
    groups.innerHTML = `<div class="card empty">No market matches this filter.</div>`;
    return;
  }
  const byTopic = new Map(TOPIC_ORDER.map((t) => [t, []]));
  for (const m of visible) {
    if (!byTopic.has(m.topic)) byTopic.set(m.topic, []);
    byTopic.get(m.topic).push(m);
  }

  groups.innerHTML = TOPIC_ORDER.filter((t) => byTopic.get(t)?.length).map((topic) => {
    const markets = byTopic.get(topic);
    const byEvent = new Map();
    for (const m of markets) {
      const key = m.eventTicker || m.ticker;
      if (!byEvent.has(key)) byEvent.set(key, []);
      byEvent.get(key).push(m);
    }
    const events = [...byEvent.entries()].sort((a, b) => b[1].length - a[1].length);
    return `<section>
      <div class="toolbar" style="margin-bottom:8px">
        <h2 style="margin:0">${esc(TOPIC_LABELS[topic])}</h2>
        <span class="badge">${esc(int(markets.length))} markets</span>
        <span class="badge">${esc(int(events.length))} events</span>
        <a class="small" href="categories/${topic}.html" style="margin-left:auto">topic page →</a>
      </div>
      <div class="table-wrap"><table class="compact">
        <thead><tr>
          <th>Market</th><th>Event</th><th class="num">YES bid</th><th class="num">YES ask</th>
          <th class="num">24h vol</th><th class="num">Open interest</th><th>State</th><th class="num">Observed</th><th>Source</th>
        </tr></thead>
        <tbody>
          ${events.map(([event, list]) => list.map((m, i) => {
            const s = stateOf(m);
            return `<tr>
              <td>${i === 0 ? '' : '<span class="dim" style="padding-left:12px">↳</span> '}<a href="market.html?t=${encodeURIComponent(m.ticker)}">${esc(m.title ?? m.ticker)}</a>
                <span class="sub mono">${esc(m.ticker)}</span></td>
              <td class="mono small">${i === 0 ? esc(event) : ''}</td>
              <td class="num">${esc(cents(m.yesBid))}</td>
              <td class="num">${esc(cents(m.yesAsk))}</td>
              <td class="num">${esc(int(m.volume24h))}</td>
              <td class="num">${esc(int(m.openInterest))}</td>
              <td><span class="badge ${s.cls}">${esc(s.label)}</span></td>
              <td class="num dim">${esc(timeAgo(m.observedAt))}</td>
              <td class="src">${sourceLink(m.sourceUrl, 'market')}</td>
            </tr>`;
          }).join('')).join('')}
        </tbody>
      </table></div>
    </section>`;
  }).join('');
}

async function init() {
  try {
    const snap = await loadLocal('data/snapshot.json');
    rows = (snap.markets ?? []).filter((m) => m.topic).map((m) => ({ ...m, observedAt: m.observedAt ?? snap.meta?.capturedAt }));
    renderBanner(document.getElementById('data-banner'), {
      state: 'snapshot',
      headline: `${rows.length} markets in the committed capture`,
      detail: 'Open the Collect live demo data workflow to refresh. Each row links to its Kalshi record.',
      at: snap.meta?.capturedAt,
    });
  } catch (err) {
    renderBanner(document.getElementById('data-banner'), { state: 'error', headline: 'Capture failed to load', detail: err.message });
  }
  try {
    const live = await loadLocal('data/live/state.json');
    resolutions = live.resolutions ?? {};
  } catch { resolutions = {}; }
  render();
}

document.getElementById('state-filter')?.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-state]');
  if (!btn) return;
  filterState = btn.dataset.state;
  for (const b of document.querySelectorAll('#state-filter button')) b.setAttribute('aria-pressed', String(b === btn));
  render();
});

document.getElementById('q')?.addEventListener('input', (e) => { query = e.target.value.trim(); render(); });

init();
