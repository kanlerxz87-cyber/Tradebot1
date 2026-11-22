// The two scrolling chats.
//
// Left: every observed >= $0.10 swing.
// Right: the subset this project's research score likes (model-filtered).
//
// The brief calls the second one "high ROI". No ROI is claimed: the score is a
// triage heuristic, its components are shown per row, and it is labelled
// everywhere as a project formula rather than an exchange figure.

import { clock, cents, money, signedMoney, esc, dash, timeAgo, topicLabel } from './common.js';

const MAX_ROWS = 250;

export function createStream(root, { onCount } = {}) {
  root.innerHTML = '<div class="chat-empty">Waiting for the first observation…</div>';
  const seen = new Set();
  let paused = false;
  let count = 0;

  function render(row, { filtered = false } = {}) {
    const up = (row.delta ?? 0) >= 0;
    const el = document.createElement('article');
    el.className = 'msg';
    el.innerHTML = `
      <div class="row1">
        <span class="t">${esc(clock(row.observedAt))}</span>
        ${row.isDemoExample ? '<span class="badge warn">worked example</span>' : ''}
        <span class="badge ${up ? 'up' : 'down'}">${up ? '▲' : '▼'} ${esc(signedMoney(Math.abs(row.delta ?? 0), 2))}</span>
        <span class="badge">${esc(topicLabel(row.topic))}</span>
        ${filtered ? `<span class="badge info">score ${esc(row.score ?? dash)}</span>` : ''}
        ${row.isDemoExample ? '<span class="badge">not a live swing</span>' : ''}
      </div>
      <div class="title" style="margin-top:4px">${esc(row.title || row.marketTicker)}</div>
      <div class="meta">
        <span class="mono">${esc(cents(row.from))} → ${esc(cents(row.to))}</span>
        <span class="mono">${esc(row.marketTicker)}</span>
        ${row.crossDepthContracts != null ? `<span>${esc(Math.round(row.crossDepthContracts).toLocaleString('en-US'))} contracts at the touch</span>` : ''}
        <a href="${esc(row.marketUrl ?? '#')}" target="_blank" rel="noopener noreferrer nofollow">market ↗</a>
      </div>
      ${filtered && row.score != null ? `<div class="bar" title="research score ${esc(row.score)} of 100"><i style="width:${Math.max(0, Math.min(100, row.score))}%"></i></div>` : ''}
    `;
    return el;
  }

  function push(rows, opts) {
    const fresh = [];
    for (const row of rows) {
      if (!row?.id || seen.has(row.id)) continue;
      seen.add(row.id);
      fresh.push(row);
    }
    if (!fresh.length) return 0;

    const empty = root.querySelector('.chat-empty');
    if (empty) empty.remove();

    // Newest first, matching the committed feed's ordering.
    for (const row of fresh.reverse()) {
      root.prepend(render(row, opts));
      count += 1;
    }
    while (root.children.length > MAX_ROWS) root.lastElementChild.remove();
    if (!paused) root.scrollTop = 0;
    onCount?.(count);
    return fresh.length;
  }

  root.addEventListener('mouseenter', () => { paused = true; });
  root.addEventListener('mouseleave', () => { paused = false; });
  root.addEventListener('focusin', () => { paused = true; });
  root.addEventListener('focusout', () => { paused = false; });

  return { push, size: () => count };
}

export function emptyState(root, message) {
  root.innerHTML = `<div class="chat-empty">${esc(message)}</div>`;
}

export { MAX_ROWS };
