/* common.js — shared chrome (nav/footer), formatting helpers, storage.
   No dependencies. Every page gets the same header/footer so they stay in sync. */
'use strict';

const SITE = {
  repoUrl: 'https://github.com/kanlerxz87-cyber/Tradebot1',
  pagesUrl: 'https://kanlerxz87-cyber.github.io/Tradebot1/',
  demoRest: 'https://external-api.demo.kalshi.co/trade-api/v2',
  demoRestAlt: 'https://demo-api.kalshi.co/trade-api/v2',
  demoWs: 'wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2',
  demoSite: 'https://demo.kalshi.com',
  docsRoot: 'https://docs.kalshi.com',
  updated: '2026-11-22',
};

const NAV_ITEMS = [
  ['index.html', 'Overview'],
  ['dashboard.html', 'Live Dashboard'],
  ['events.html', 'Events & Resolution'],
  ['strategies.html', 'Strategy Lab'],
  ['portfolio.html', 'Portfolio'],
  ['summary.html', 'Executive Summary'],
  ['verification.html', 'Verification'],
  ['flagged.html', 'Flagged'],
  ['repo-review.html', 'Repo Review'],
  ['suggestions.html', 'Suggestions'],
];

function renderChrome() {
  const page = document.body.dataset.page || '';
  const headerEl = document.getElementById('site-header');
  const footerEl = document.getElementById('site-footer');
  if (headerEl) {
    const links = NAV_ITEMS.map(([href, label]) => {
      const active = href === page ? ' class="active"' : '';
      return `<a href="${href}"${active}>${label}</a>`;
    }).join('');
    headerEl.innerHTML = `
      <div class="header-inner">
        <a class="brand" href="index.html" aria-label="Tradebot1 home">
          <span class="logo">T</span>
          <span>Tradebot1<small>Kalshi Demo Command Center</small></span>
        </a>
        <button class="nav-toggle" id="navToggle" aria-label="Toggle navigation">☰</button>
        <nav class="nav" id="siteNav">${links}</nav>
      </div>`;
    const toggle = headerEl.querySelector('#navToggle');
    const nav = headerEl.querySelector('#siteNav');
    toggle.addEventListener('click', () => nav.classList.toggle('open'));
  }
  if (footerEl) {
    footerEl.innerHTML = `
      <div class="footer-inner">
        <div>
          <strong>Tradebot1 — Kalshi Demo Command Center</strong><br>
          Data source: Kalshi Trade API v2 — demo environment (mock funds). Demo REST:
          <code>https://external-api.demo.kalshi.co/trade-api/v2</code>.<br>
          Not financial advice. Kalshi is a CFTC-designated contract market; this is an independent project,
          not affiliated with or endorsed by Kalshi. Demo markets use simulated money.
        </div>
        <div style="text-align:right">
          <a href="${SITE.repoUrl}">GitHub repo</a> ·
          <a href="${SITE.pagesUrl}">Live site</a> ·
          <a href="${SITE.docsRoot}">Kalshi API docs</a><br>
          Site updated: ${SITE.updated} (UTC) · Live values load in your browser; nothing is fabricated server-side.<br>
          <a href="flagged.html">Flagged for Review</a> · <a href="verification.html">Verification</a>
        </div>
      </div>`;
  }
}

/* ---------- formatting ---------- */
const fmtUsd = (n, digits = 2) => (n == null || Number.isNaN(n)) ? '—' :
  (n < 0 ? '-$' : '$') + Math.abs(n).toFixed(digits);
const fmtContracts = (n) => (n == null || Number.isNaN(n)) ? '—' :
  Math.round(n).toLocaleString('en-US');
const fmtPct = (n, digits = 1) => (n == null || Number.isNaN(n)) ? '—' : (n >= 0 ? '+' : '') + (n * 100).toFixed(digits) + '%';
const fmtSignedUsd = (n, digits = 2) => (n == null || Number.isNaN(n)) ? '—' :
  (n >= 0 ? '+' : '-') + '$' + Math.abs(n).toFixed(digits);
const fmtCents = (p) => (p == null || Number.isNaN(p)) ? '—' : Math.round(p * 100) + '¢';
const fmtTime = (d) => new Date(d).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
const fmtDateTime = (d) => new Date(d).toLocaleString('en-US', { hour12: false });
const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- storage (localStorage, prefixed) ---------- */
const store = {
  get(key, fallback) {
    try { const raw = localStorage.getItem('tbs_' + key); return raw == null ? fallback : JSON.parse(raw); }
    catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem('tbs_' + key, JSON.stringify(value)); } catch { /* quota */ } },
  remove(key) { try { localStorage.removeItem('tbs_' + key); } catch { /* ignore */ } },
};

/* ---------- misc ---------- */
function toast(msg, ms = 2600) {
  let el = document.getElementById('toast');
  if (!el) { el = document.createElement('div'); el.id = 'toast'; el.className = 'toast'; document.body.appendChild(el); }
  el.textContent = msg; el.style.display = 'block';
  clearTimeout(el._t);
  el._t = setTimeout(() => { el.style.display = 'none'; }, ms);
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/* fetch with timeout + one host fallback. Returns { ok, data, error } */
async function fetchJson(url, options = {}, timeoutMs = 9000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: ctrl.signal });
    clearTimeout(t);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    clearTimeout(t);
    return { ok: false, status: 0, error: String(err && err.message || err) };
  }
}

document.addEventListener('DOMContentLoaded', renderChrome);
