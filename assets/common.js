// Shared browser helpers: formatting, the data-source banner, and the live
// feed loader that prefers the official API and falls back to the committed
// snapshot.
//
// Rule that holds everywhere in this file: a missing value is rendered as a
// dash and never as 0. A price that was not observed is not a price.

export const DEMO_REST = 'https://external-api.demo.kalshi.co/trade-api/v2';
export const DEMO_REST_ALT = 'https://demo-api.kalshi.co/trade-api/v2';

export const dash = '—';

/**
 * Relative prefix from the current page back to the site root.
 * Category pages live in /categories/, everything else at the root.
 */
export const ROOT_PREFIX = /\/categories\/[^/]*$/.test(location.pathname) ? '../' : '';

/** Build a same-site URL from the current page. */
export function sitePath(rel) { return ROOT_PREFIX + rel; }

export function money(v, digits = 2) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return dash;
  return `$${Number(v).toFixed(digits)}`;
}

export function cents(v) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return dash;
  return `${(Number(v) * 100).toFixed(Number(v) * 100 % 1 === 0 ? 0 : 1)}¢`;
}

export function num(v, digits = 2) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return dash;
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function int(v) {
  if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return dash;
  return Math.round(Number(v)).toLocaleString('en-US');
}

export function signedMoney(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return dash;
  const n = Number(v);
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}$${Math.abs(n).toFixed(digits)}`;
}

export function pct(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return dash;
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

export function timeAgo(iso) {
  if (!iso) return dash;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return dash;
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function clock(iso) {
  if (!iso) return dash;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return dash;
  return d.toISOString().slice(11, 19) + 'Z';
}

export function stamp(iso) {
  if (!iso) return dash;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return dash;
  return d.toISOString().replace('T', ' ').slice(0, 16) + 'Z';
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** A source link. Every table row uses one. */
export function sourceLink(url, label = 'source') {
  if (!url) return `<span class="dim">${dash}</span>`;
  return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer nofollow">${esc(label)}</a>`;
}

export function topicClass(id) { return `badge info`; }

export function topicLabel(id) {
  return TOPIC_LABELS[id] ?? (id ? String(id) : 'unclassified');
}

export const TOPIC_LABELS = {
  gas: 'Gas prices', elections: 'Elections', culture: 'Culture', crypto: 'Crypto', golf: 'Golf',
};

/** Fetch JSON with a timeout, so a hanging API does not freeze the page. */
export async function fetchJson(url, timeoutMs = 9000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctl.signal, headers: { accept: 'application/json' }, mode: 'cors' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

/**
 * Load a local JSON file published next to the page.
 * Uses a cache-buster so a returning visitor sees the newest committed data.
 */
export async function loadLocal(path) {
  const url = new URL(path, location.href);
  url.searchParams.set('_', String(Math.floor(Date.now() / 60000))); // minute granularity
  const res = await fetch(url.toString(), { headers: { accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`);
  return res.json();
}

/**
 * Probe the public demo API from this browser.
 * Returns { ok, root, status } and never throws.
 */
export async function probeApi() {
  for (const root of [DEMO_REST, DEMO_REST_ALT]) {
    try {
      const data = await fetchJson(`${root}/exchange/status`, 6000);
      return { ok: true, root, data, at: new Date().toISOString() };
    } catch (err) {
      // try the next host
      var last = err.message;
    }
  }
  return { ok: false, root: null, error: last ?? 'unreachable', at: new Date().toISOString() };
}

/**
 * Render the data-source banner into an element.
 * state: 'live' | 'snapshot' | 'error'
 */
export function renderBanner(el, { state, headline, detail, at }) {
  if (!el) return;
  el.dataset.state = state;
  el.innerHTML = `<span class="led" aria-hidden="true"></span>
    <strong>${esc(headline)}</strong>
    <span class="muted">${esc(detail)}</span>
    ${at ? `<span class="dim" style="margin-left:auto">${esc(stamp(at))} · ${esc(timeAgo(at))}</span>` : ''}`;
}

/** Group rows by topic id, preserving the canonical topic order. */
export function byTopic(rows) {
  const out = new Map([['gas', []], ['elections', []], ['culture', []], ['crypto', []], ['golf', []]]);
  for (const r of rows ?? []) {
    if (!out.has(r.topic)) out.set(r.topic, []);
    out.get(r.topic).push(r);
  }
  return out;
}

/** Escape-safe HTML template tag. Interpolations are escaped unless marked raw. */
export function html(strings, ...values) {
  return strings.reduce((acc, s, i) => {
    const v = values[i - 1];
    if (v === undefined) return acc + s;
    if (v && typeof v === 'object' && v.__raw) return acc + v.value + s;
    if (Array.isArray(v)) return acc + v.map((x) => (x && x.__raw ? x.value : esc(x))).join('') + s;
    return acc + esc(v) + s;
  });
}
export function raw(value) { return { __raw: true, value }; }
