// Drives the two scrolling feeds and the observation log on dashboard.html.

import { loadLocal, renderBanner, cents, esc, dash, timeAgo, clock, signedMoney, sourceLink, TOPIC_LABELS } from './common.js';
import { createStream, emptyState } from './alerts-stream.js';

const REFRESH_MS = 30000;

const el = {
  banner: document.getElementById('data-banner'),
  all: document.getElementById('feed-all'),
  filtered: document.getElementById('feed-filtered'),
  countAll: document.getElementById('feed-a-count'),
  countFiltered: document.getElementById('feed-b-count'),
  windowAll: document.getElementById('feed-a-window'),
  windowFiltered: document.getElementById('feed-b-window'),
  obs: document.querySelector('#obs-table tbody'),
};

const streams = {
  all: createStream(el.all, { onCount: (c) => { el.countAll.textContent = c; } }),
  filtered: createStream(el.filtered, { onCount: (c) => { el.countFiltered.textContent = c; } }),
};

let feed = null;
let filterTopic = 'all';
let onlyQualifying = true;

async function load() {
  try {
    feed = await loadLocal('data/live/feed.json');
  } catch (err) {
    feed = { alerts: [], filteredIds: [], updatedAt: null, threshold: 0.1 };
    emptyState(el.all, 'The committed alert record could not be loaded.');
    emptyState(el.filtered, 'The committed alert record could not be loaded.');
  }
  const alerts = feed.alerts ?? [];
  const filteredRows = alerts.filter((a) => (feed.filteredIds ?? []).includes(a.id));

  if (!alerts.length) {
    emptyState(el.all, 'No qualifying swing has been recorded yet. The collector writes this record on a schedule; an empty feed can mean genuinely quiet markets, or that the collector has not run since this data was committed.');
    emptyState(el.filtered, 'Nothing has passed the research filter yet.');
  } else {
    streams.all.push(alerts);
    streams.filtered.push(filteredRows, { filtered: true });
  }

  el.countAll.textContent = alerts.length;
  el.countFiltered.textContent = filteredRows.length;
  el.windowAll.textContent = feed.updatedAt ? `record ${timeAgo(feed.updatedAt)}` : '';
  el.windowFiltered.textContent = feed.updatedAt ? `record ${timeAgo(feed.updatedAt)}` : '';

  renderBanner(el.banner, {
    state: alerts.length ? 'snapshot' : 'error',
    headline: alerts.length ? 'Committed alert record' : 'No recorded swings yet',
    detail: alerts.length
      ? `Threshold $${(feed.threshold ?? 0.1).toFixed(2)}. Written by the scheduled collector, so it keeps running with no browser open.`
      : 'The collector runs on a schedule and appends here. Nothing has crossed the threshold in the record so far.',
    at: feed.updatedAt,
  });

  renderObs();
}

function renderObs() {
  const rows = (feed?.alerts ?? [])
    .filter((a) => (filterTopic === 'all' ? true : a.topic === filterTopic))
    .slice(0, 300);
  if (!rows.length) {
    el.obs.innerHTML = `<tr><td colspan="8" class="empty">No rows for this filter.</td></tr>`;
    return;
  }
  el.obs.innerHTML = rows.map((a) => {
    const up = (a.delta ?? 0) >= 0;
    return `<tr>
      <td class="mono nowrap">${esc(clock(a.observedAt))}<span class="sub">${esc(timeAgo(a.observedAt))}</span></td>
      <td>${esc(a.title ?? a.marketTicker)}<span class="sub mono">${esc(a.marketTicker)}</span></td>
      <td><span class="badge">${esc(TOPIC_LABELS[a.topic] ?? a.topic)}</span>${a.isDemoExample ? ' <span class="badge warn">worked example</span>' : ''}</td>
      <td class="num">${esc(cents(a.from))}</td>
      <td class="num">${esc(cents(a.to))}</td>
      <td class="num">${esc(cents((a.from + a.to) / 2))}</td>
      <td class="num ${up ? 'up' : 'down'}">${esc(signedMoney(a.delta))}</td>
      <td class="src">${sourceLink(a.marketUrl, 'market')}</td>
    </tr>`;
  }).join('');
}

document.getElementById('topic-filter')?.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-topic]');
  if (!btn) return;
  filterTopic = btn.dataset.topic;
  for (const b of document.querySelectorAll('#topic-filter button')) b.setAttribute('aria-pressed', String(b === btn));
  renderObs();
});

load().catch((err) => {
  renderBanner(el.banner, { state: 'error', headline: 'Alert record failed to load', detail: err.message });
});

// A light refresh keeps an open tab current without a page reload.
setInterval(() => { load().catch(() => {}); }, REFRESH_MS);
